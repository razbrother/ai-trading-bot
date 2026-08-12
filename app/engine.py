import asyncio
from datetime import datetime
from app.settings import settings
from app.models import Action,Mode,Position,Status
from app.market import score
from app.risk import Reject
from app.data_policy import validate_entry_context, DataPolicyError
from app.fake_data_analyzer import analyze_snapshot
from app.learning import PreviousTradeAnalyzer

class Engine:
    def __init__(self,market,news,history,ai,risk,broker,db,notify):
        self.market=market;self.news=news;self.history=history;self.ai=ai;self.risk=risk;self.broker=broker;self.db=db;self.notify=notify
        self.auto=settings.auto_start;self.paused=False;self.reason="";self.last="No decision";self.lock=asyncio.Lock();self.learning=PreviousTradeAnalyzer(db);self.last_candidates=[]
    def context(self):
        n,p=self.db.today(datetime.now(settings.tz).date().isoformat())
        return {"mode":settings.trading_mode.value,"trades_today":n,"pnl":p,
          "positions":[x.model_dump(mode="json") for x in self.db.positions()]}
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
            anomalies=analyze_snapshot(c.snapshot)
            if settings.trading_mode.value=="LIVE" and anomalies:
                self.paused=True;self.reason="market-data anomalies: "+",".join(anomalies)
                raise RuntimeError(self.reason)
            if c.score<settings.min_technical_score:return f"HOLD {c.snapshot.symbol} score={c.score}"
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
            try:o=self.risk.validate(c,d,self.db.positions(),n,pnl)
            except Reject as e:return self.last+" REJECTED "+str(e)
            filled=await self.verify(await self.broker.enter(o))
            pos=Position(symbol=o.symbol,qty=o.qty,side=o.action,avg_price=filled.avg_price or o.entry,
              stop=o.stop,target=o.target,opened_at=datetime.now(settings.tz),broker_id=filled.broker_id)
            pos.stop_order_id=await self.broker.place_protective_stop(pos)
            self.db.save_pos(pos);await self.notify(f"ENTRY {pos.side.value} {pos.qty} {pos.symbol} @ {pos.avg_price}")
            return "opened "+pos.symbol
    async def monitor(self):
        for p in self.db.positions():
            i=next((x for x in settings.instruments if x.symbol==p.symbol),None)
            if i is None:
                self.paused=True;self.reason=f"position {p.symbol} has no matching instrument in SYMBOLS"
                await self.notify("EMERGENCY PAUSE\n"+self.reason);continue
            s=await self.market.snapshot(i)
            p.ltp=s.ltp;p.upnl=((s.ltp-p.avg_price) if p.side==Action.BUY else (p.avg_price-s.ltp))*p.qty
            self.db.save_pos(p);reason=None
            if p.side==Action.BUY:
                if s.ltp<=p.stop:reason="STOP"
                elif s.ltp>=p.target:reason="TARGET"
            else:
                if s.ltp>=p.stop:reason="STOP"
                elif s.ltp<=p.target:reason="TARGET"
            if datetime.now(settings.tz).time()>=settings.tm(settings.force_exit):reason="FORCE_EXIT"
            if reason:
                x=await self.verify(await self.broker.exit(p,s.ltp,reason));ep=x.avg_price or s.ltp
                cost_bps=settings.paper_cost_bps if settings.trading_mode==Mode.PAPER else settings.live_cost_bps
                costs=(p.avg_price+ep)*p.qty*cost_bps/10000
                net=self.db.close(p,ep,costs,reason);await self.notify(f"EXIT {p.symbol} net ₹{net:.2f}")
    async def reconcile(self):
        bp={x.symbol:x for x in await self.broker.positions()};ip={x.symbol:x for x in self.db.positions()}
        if set(bp)!=set(ip):
            self.paused=True;self.reason=f"reconcile mismatch broker={list(bp)} internal={list(ip)}"
            await self.notify("EMERGENCY PAUSE\n"+self.reason);raise RuntimeError(self.reason)
        for s in bp:
            if bp[s].qty!=ip[s].qty or bp[s].side!=ip[s].side:
                self.paused=True;self.reason="quantity/side mismatch";raise RuntimeError(self.reason)
        return "reconciliation OK"
