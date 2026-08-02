from datetime import datetime
from app.settings import settings
from app.models import Action,ValidOrder

class Reject(ValueError):pass
class Risk:
    def validate(self,c,d,positions,trades,pnl):
        now=datetime.now(settings.tz);s=c.snapshot
        if not(settings.tm(settings.entry_start)<=now.time()<=settings.tm(settings.last_entry)):raise Reject("time")
        if (now-s.timestamp.astimezone(settings.tz)).total_seconds()>settings.max_signal_age_seconds:raise Reject("stale")
        if c.score<settings.min_technical_score:raise Reject("score")
        if d.confidence<settings.ai_min_confidence:raise Reject("confidence")
        if d.action not in {Action.BUY,Action.SELL}:raise Reject("not entry")
        if len(positions)>=settings.max_open_positions:raise Reject("open position limit")
        if trades>=settings.max_trades_per_day:raise Reject("daily trade limit")
        if pnl<=-settings.max_daily_loss:raise Reject("daily loss stop")
        if pnl>=settings.hard_daily_profit:raise Reject("daily profit stop")
        if s.spread_pct>settings.max_spread_pct or s.news_risk=="HIGH":raise Reject("market quality")
        e,st,tg=float(d.entry),float(d.stop),float(d.target)
        if abs(e-s.ltp)/s.ltp>.005:raise Reject("chasing")
        if d.action==Action.BUY:
            if not st<e<tg:raise Reject("price order")
            ru=e-st;reward=tg-e
        else:
            if not tg<e<st:raise Reject("price order")
            ru=st-e;reward=e-tg
        mult=ru/s.atr
        if not settings.min_stop_atr_multiple<=mult<=settings.max_stop_atr_multiple:raise Reject("ATR stop")
        rr=reward/ru
        if rr<settings.min_reward_risk:raise Reject("RR")
        allowed=settings.starting_capital*settings.max_risk_per_trade_pct
        qty=min(int(allowed//ru),int(settings.max_position_value//e),int(settings.starting_capital//e))
        if qty<1:raise Reject("quantity")
        return ValidOrder(symbol=s.symbol,action=d.action,qty=qty,entry=e,stop=st,target=tg,
          risk=qty*ru,rr=rr,confidence=d.confidence,score=c.score,signal_time=s.timestamp)
