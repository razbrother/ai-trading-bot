import asyncio
from datetime import datetime
from app.settings import settings
from app.models import Action,Decision,Mode,Position,Status
from app.market import score
from app.risk import Reject
from app.data_policy import validate_entry_context, DataPolicyError
from app.fake_data_analyzer import analyze_snapshot
from app.learning import PreviousTradeAnalyzer
from app.ai import PortfolioAssistant

class Engine:
    def __init__(self,market,news,history,ai,risk,broker,db,notify):
        self.market=market;self.news=news;self.history=history;self.ai=ai;self.risk=risk;self.broker=broker;self.db=db;self.notify=notify
        self.assistant=PortfolioAssistant(notify)
        self.auto=settings.auto_start
        # paused/reason are DB-backed so an unplanned restart can't silently
        # erase a safety pause caused by a real problem (anomalies, a reconcile
        # mismatch). auto is intentionally NOT persisted: every restart requires
        # an explicit /start_auto + confirm before new entries resume.
        self._paused=db.get_state("paused","False")=="True";self._reason=db.get_state("reason","")
        self.last="No decision";self.lock=asyncio.Lock();self.learning=PreviousTradeAnalyzer(db);self.last_candidates=[]
    @property
    def paused(self):return self._paused
    @paused.setter
    def paused(self,v):self._paused=v;self.db.set_state("paused",str(v))
    @property
    def reason(self):return self._reason
    @reason.setter
    def reason(self,v):self._reason=v;self.db.set_state("reason",v)
    def context(self):
        n,p=self.db.today(datetime.now(settings.tz).date().isoformat())
        return {"mode":settings.trading_mode.value,"trades_today":n,"pnl":p,
          "positions":[x.model_dump(mode="json") for x in self.db.positions()]}
    async def ask(self,question):
        ctx={"report":self.db.report(),"today":self.context(),
          "watchlist":[{"symbol":c.snapshot.symbol,"score":c.score} for c in self.last_candidates],
          "last_decision":self.last,"auto":self.auto,"paused":self.paused,"reason":self.reason}
        return await self.assistant.answer(question,ctx)
    async def verify(self,o):
        self.db.order(o)
        if o.status==Status.FILLED:return o
        if o.status in {Status.REJECTED,Status.CANCELLED,Status.UNKNOWN}:raise RuntimeError("order failed/unknown")
        for _ in range(10):
            await asyncio.sleep(2);o=await self.broker.get_order(o.broker_id,o.local_id);self.db.order(o)
            if o.status==Status.FILLED:return o
            if o.status in {Status.REJECTED,Status.CANCELLED}:raise RuntimeError("order rejected")
        raise RuntimeError("order status uncertain")
    async def scan(self):
        async with self.lock:
            if not self.auto:return "auto off"
            if self.paused:return "paused: "+self.reason
            if self.db.positions():return "position exists"
            cs=sorted([score(x) for x in await self.market.snapshots(settings.instruments)],
              key=lambda x:x.score,reverse=True)
            if not cs:return "no data"
            eligible=cs[:settings.top_candidates];self.last_candidates=eligible
            c=eligible[0]
            if c.score<settings.min_technical_score:return f"HOLD {c.snapshot.symbol} score={c.score}"
            return await self._decide_and_enter(c,eligible)
    async def _resolve(self,symbol):
        symbol=symbol.upper()
        i=next((x for x in settings.instruments if x.symbol==symbol),None)
        if i is not None:return i
        if hasattr(self.market,"resolve"):return await self.market.resolve(symbol)
        return None
    async def pick(self,symbol):
        async with self.lock:
            if self.paused:return "paused: "+self.reason
            if self.db.positions():return "position exists"
            i=await self._resolve(symbol)
            if i is None:return f"{symbol} not found or not intraday-tradeable on NSE"
            c=score(await self.market.snapshot(i))
            self.last_candidates=[c]
            return await self._decide_and_enter(c,[c],skip_score_gate=True)
    async def manual(self,symbol,action):
        # User-directed BUY/SELL: gated on auto-trading being ON (same safety
        # switch as the automated path) rather than a separate /confirm step.
        # Stop/target are computed from the same ATR-based risk math the AI
        # path uses (midpoint of the allowed stop-ATR range, reward at the
        # configured min reward:risk), then run through the normal risk gate -
        # only the AI's own BUY/SELL/confidence choice is skipped.
        async with self.lock:
            if not self.auto:return "Auto trading is off. Run /start_auto first to use /buy and /sell."
            if self.paused:return "paused: "+self.reason
            if self.db.positions():return "position exists"
            i=await self._resolve(symbol)
            if i is None:return f"{symbol} not found or not intraday-tradeable on NSE"
            s=await self.market.snapshot(i)
            c=score(s)
            self.last_candidates=[c]
            anomalies=analyze_snapshot(s)
            if settings.trading_mode.value=="LIVE" and anomalies:
                self.paused=True;self.reason="market-data anomalies: "+",".join(anomalies)
                raise RuntimeError(self.reason)
            news_ctx=await self.news.get(s.symbol)
            history_ctx=await self.history.get(s.symbol)
            validate_entry_context(s,news_ctx,history_ctx,settings.trading_mode)
            mult=(settings.min_stop_atr_multiple+settings.max_stop_atr_multiple)/2
            risk_per_share=mult*s.atr;reward_per_share=settings.min_reward_risk*risk_per_share
            if action==Action.BUY:
                entry=s.ltp;stop=round(entry-risk_per_share,2);target=round(entry+reward_per_share,2)
            else:
                entry=s.ltp;stop=round(entry+risk_per_share,2);target=round(entry-reward_per_share,2)
            d=Decision(action=action,symbol=s.symbol,entry=entry,stop=stop,target=target,
              confidence=1.0,hold_minutes=30,reasons=["manual"],rationale="Manual user-directed trade")
            n,pnl=self.db.today(datetime.now(settings.tz).date().isoformat())
            try:o=self.risk.validate(c,d,self.db.positions(),n,pnl,skip_score_gate=True)
            except Reject as e:return "REJECTED "+str(e)
            filled=await self.verify(await self.broker.enter(o))
            pos=Position(symbol=o.symbol,qty=o.qty,side=o.action,avg_price=filled.avg_price or o.entry,
              stop=o.stop,target=o.target,opened_at=datetime.now(settings.tz),broker_id=filled.broker_id)
            pos.peak_price=pos.avg_price;pos.initial_stop=pos.stop
            pos.stop_order_id=await self.broker.place_protective_stop(pos)
            self.db.save_pos(pos)
            await self.notify(f"MANUAL {pos.side.value} {pos.qty} {pos.symbol} @ {pos.avg_price}")
            return (f"opened {pos.symbol} {pos.side.value} qty={pos.qty} "
              f"entry={pos.avg_price} stop={pos.stop} target={pos.target}")
    async def check_delivery(self,symbol):
        # Advisory only - never places an order or touches positions, so it
        # deliberately skips the trading lock/gates and the data-policy staleness
        # gate (a freshly-listed symbol may not have min_history_candles yet,
        # which is fine for an opinion but would hard-block a real entry).
        i=await self._resolve(symbol)
        if i is None:return f"{symbol} not found or not intraday-tradeable on NSE"
        c=score(await self.market.snapshot(i))
        news_ctx=await self.news.get(c.snapshot.symbol)
        history_ctx=await self.history.get(c.snapshot.symbol)
        ctx=self.context()
        ctx["news"]=news_ctx.model_dump(mode="json")
        ctx["history"]=history_ctx.model_dump(mode="json")
        ctx["own_previous_trades"]={c.snapshot.symbol:self.learning.evidence(c.snapshot.symbol)}
        result=await self.ai.run([c],ctx)
        conf=min(result.gemini.confidence,result.openai.confidence)
        good=result.gemini.action==Action.BUY and result.openai.action==Action.BUY and conf>=settings.delivery_check_min_confidence
        verdict="YES - good to hold overnight" if good else "NO - not confident enough to hold overnight"
        return (f"{verdict}\n{c.snapshot.symbol}: Gemini={result.gemini.action.value}/{result.gemini.confidence:.2f} "
          f"OpenAI={result.openai.action.value}/{result.openai.confidence:.2f} "
          f"(needs both BUY and confidence>={settings.delivery_check_min_confidence:.2f})")
    async def _decide_and_enter(self,c,eligible,skip_score_gate=False):
        anomalies=analyze_snapshot(c.snapshot)
        if settings.trading_mode.value=="LIVE" and anomalies:
            self.paused=True;self.reason="market-data anomalies: "+",".join(anomalies)
            raise RuntimeError(self.reason)
        news_ctx=await self.news.get(c.snapshot.symbol)
        history_ctx=await self.history.get(c.snapshot.symbol)
        validate_entry_context(c.snapshot,news_ctx,history_ctx,settings.trading_mode)
        ctx=self.context()
        ctx["news"]=news_ctx.model_dump(mode="json")
        ctx["history"]=history_ctx.model_dump(mode="json")
        ctx["own_previous_trades"]={x.snapshot.symbol:self.learning.evidence(x.snapshot.symbol) for x in eligible}
        result=await self.ai.run(eligible,ctx)
        c=result.candidate or c
        self.db.decision("gemini",result.gemini);self.db.decision("openai",result.openai)
        self.last=(f"Gemini={result.gemini.action.value}/{result.gemini.confidence:.2f} "
          f"OpenAI={result.openai.action.value}/{result.openai.confidence:.2f} "
          f"agreement={result.score}% approved={result.approved}")
        if not result.approved or result.final is None:
            if result.reasons:self.last+=" reasons="+",".join(result.reasons)
            return self.last
        d=result.final
        n,pnl=self.db.today(datetime.now(settings.tz).date().isoformat())
        try:o=self.risk.validate(c,d,self.db.positions(),n,pnl,skip_score_gate=skip_score_gate)
        except Reject as e:return self.last+" REJECTED "+str(e)
        filled=await self.verify(await self.broker.enter(o))
        pos=Position(symbol=o.symbol,qty=o.qty,side=o.action,avg_price=filled.avg_price or o.entry,
          stop=o.stop,target=o.target,opened_at=datetime.now(settings.tz),broker_id=filled.broker_id)
        pos.peak_price=pos.avg_price;pos.initial_stop=pos.stop
        pos.stop_order_id=await self.broker.place_protective_stop(pos)
        self.db.save_pos(pos);await self.notify(f"ENTRY {pos.side.value} {pos.qty} {pos.symbol} @ {pos.avg_price}")
        return "opened "+pos.symbol
    async def _close_position(self,p,ltp,reason):
        x=await self.verify(await self.broker.exit(p,ltp,reason));ep=x.avg_price or ltp
        cost_bps=settings.paper_cost_bps if settings.trading_mode==Mode.PAPER else settings.live_cost_bps
        costs=(p.avg_price+ep)*p.qty*cost_bps/10000
        net=self.db.close(p,ep,costs,reason);await self.notify(f"EXIT {p.symbol} net ₹{net:.2f}")
        return net
    def _momentum_favorable(self,p,s):
        fav=s.ema9>s.ema21 if p.side==Action.BUY else s.ema9<s.ema21
        return fav and s.volume_ratio>=settings.momentum_min_volume_ratio
    async def _trail(self,p,s):
        if not settings.trailing_stop_enabled:return
        peak=p.peak_price or p.avg_price
        favorable=self._momentum_favorable(p,s)
        mult=settings.trailing_atr_multiple
        if not favorable:mult*=settings.momentum_stall_tighten_factor
        now=datetime.now(settings.tz)
        fe=datetime.combine(now.date(),settings.tm(settings.force_exit),tzinfo=settings.tz)
        mins_left=(fe-now).total_seconds()/60
        if 0<=mins_left<=settings.eod_tighten_minutes:mult*=settings.eod_tighten_factor
        risk=abs(p.avg_price-(p.initial_stop or p.stop))
        if p.side==Action.BUY:
            peak=max(peak,s.ltp);new_stop=round(peak-mult*s.atr,2)
            if risk>0 and peak-p.avg_price>=settings.breakeven_trigger_r*risk:
                new_stop=max(new_stop,p.avg_price)
            moved=new_stop>p.stop
            if favorable and p.target-s.ltp<=settings.target_extend_trigger_atr*s.atr:
                p.target=round(p.target+settings.trailing_atr_multiple*s.atr,2)
        else:
            peak=min(peak,s.ltp);new_stop=round(peak+mult*s.atr,2)
            if risk>0 and p.avg_price-peak>=settings.breakeven_trigger_r*risk:
                new_stop=min(new_stop,p.avg_price)
            moved=new_stop<p.stop
            if favorable and s.ltp-p.target<=settings.target_extend_trigger_atr*s.atr:
                p.target=round(p.target-settings.trailing_atr_multiple*s.atr,2)
        p.peak_price=peak
        if moved:
            old=p.stop;p.stop=new_stop
            if p.stop_order_id:
                try:p.stop_order_id=await self.broker.update_protective_stop(p)
                except Exception:
                    p.stop=old
                    await self.notify(f"WARN trail stop update failed {p.symbol}")
    async def _early_invalidation(self,p,s):
        if not settings.early_invalidation_enabled or p.initial_stop is None:return False
        if (datetime.now(settings.tz)-p.opened_at).total_seconds()>settings.early_invalidation_window_seconds:return False
        planned_risk=abs(p.avg_price-p.initial_stop)
        if planned_risk<=0:return False
        adverse=(p.avg_price-s.ltp) if p.side==Action.BUY else (s.ltp-p.avg_price)
        return adverse>=settings.early_invalidation_risk_fraction*planned_risk and not self._momentum_favorable(p,s)
    async def monitor(self):
        for p in self.db.positions():
            i=next((x for x in settings.instruments if x.symbol==p.symbol),None)
            if i is None:
                self.paused=True;self.reason=f"position {p.symbol} has no matching instrument in SYMBOLS"
                await self.notify("EMERGENCY PAUSE\n"+self.reason);continue
            s=await self.market.snapshot(i)
            p.ltp=s.ltp;p.upnl=((s.ltp-p.avg_price) if p.side==Action.BUY else (p.avg_price-s.ltp))*p.qty
            await self._trail(p,s)
            self.db.save_pos(p);reason=None
            if p.side==Action.BUY:
                if s.ltp<=p.stop:reason="STOP"
                elif s.ltp>=p.target:reason="TARGET"
            else:
                if s.ltp>=p.stop:reason="STOP"
                elif s.ltp<=p.target:reason="TARGET"
            if not reason and await self._early_invalidation(p,s):reason="EARLY_INVALIDATION"
            if datetime.now(settings.tz).time()>=settings.tm(settings.force_exit):reason="FORCE_EXIT"
            if reason:await self._close_position(p,s.ltp,reason)
    async def close_all(self,reason="EMERGENCY"):
        closed=[]
        for p in self.db.positions():
            i=next((x for x in settings.instruments if x.symbol==p.symbol),None)
            if i is None:
                await self.notify(f"WARNING: cannot price {p.symbol} for {reason} close "
                  "(no matching instrument in SYMBOLS); close it manually in the broker app")
                continue
            s=await self.market.snapshot(i)
            await self._close_position(p,s.ltp,reason);closed.append(p.symbol)
        return closed
    async def reconcile(self):
        # Only reconcile symbols this bot actually trades (its configured universe,
        # plus anything already in its own DB). Holdings in other symbols are the
        # account owner's business, not this bot's, and are ignored entirely.
        ip={x.symbol:x for x in self.db.positions()}
        tracked=set(x.symbol for x in settings.instruments)|set(ip)
        bp={x.symbol:x for x in await self.broker.positions() if x.symbol in tracked}
        if set(bp)!=set(ip):
            self.paused=True;self.reason=f"reconcile mismatch broker={list(bp)} internal={list(ip)}"
            await self.notify("EMERGENCY PAUSE\n"+self.reason);raise RuntimeError(self.reason)
        for s in bp:
            if bp[s].qty!=ip[s].qty or bp[s].side!=ip[s].side:
                self.paused=True;self.reason="quantity/side mismatch";raise RuntimeError(self.reason)
        return "reconciliation OK"
