import uuid
from datetime import datetime
from app.settings import settings
from app.models import Action,Status,BrokerOrder,Position,ValidOrder
from app.execution_state import ExecutionRecord,ExecutionState
from app.groww_execution import GrowwExecutionClient
from app import groww_limits

EXEC_STATUS_MAP={ExecutionState.FILLED:Status.FILLED,ExecutionState.REJECTED:Status.REJECTED,
  ExecutionState.CANCELLED:Status.CANCELLED,ExecutionState.FAILED:Status.REJECTED,
  ExecutionState.PARTIAL:Status.PARTIAL,ExecutionState.OPEN:Status.OPEN,
  ExecutionState.ACKED:Status.OPEN,ExecutionState.SUBMITTED:Status.OPEN}
def exec_status(state):return EXEC_STATUS_MAP.get(state,Status.UNKNOWN)

class PaperBroker:
    def __init__(self):self.orders={};self.pos={}
    def fill(self,p,a):
        x=p*settings.paper_slippage_bps/10000
        return round(p+x if a==Action.BUY else p-x,2)
    async def enter(self,o:ValidOrder):
        lid=uuid.uuid4().hex;avg=self.fill(o.entry,o.action)
        x=BrokerOrder(local_id=lid,broker_id="PAPER-"+lid[:12],symbol=o.symbol,action=o.action,
          qty=o.qty,filled_qty=o.qty,requested_price=o.entry,avg_price=avg,status="FILLED",
          updated_at=datetime.now(settings.tz))
        self.orders[x.broker_id]=x;self.pos[o.symbol]=Position(symbol=o.symbol,qty=o.qty,side=o.action,
          avg_price=avg,stop=o.stop,target=o.target,opened_at=datetime.now(settings.tz),
          broker_id=x.broker_id,ltp=avg)
        return x
    async def get_order(self,bid,lid):return self.orders[bid]
    async def positions(self):return list(self.pos.values())
    async def exit(self,p,price,reason):
        a=Action.SELL if p.side==Action.BUY else Action.BUY;lid=uuid.uuid4().hex;avg=self.fill(price,a)
        x=BrokerOrder(local_id=lid,broker_id="PAPER-"+lid[:12],symbol=p.symbol,action=a,qty=p.qty,
          filled_qty=p.qty,requested_price=price,avg_price=avg,status="FILLED",message=reason,
          updated_at=datetime.now(settings.tz));self.orders[x.broker_id]=x;self.pos.pop(p.symbol,None);return x
    async def place_protective_stop(self,p):return None

class GrowwBroker:
    def __init__(self):
        settings.validate_live()
        from growwapi import GrowwAPI
        import pyotp
        if settings.groww_totp_token and settings.groww_totp_secret:
            token=GrowwAPI.get_access_token(api_key=settings.groww_totp_token,
              totp=pyotp.TOTP(settings.groww_totp_secret).now())
        elif settings.groww_api_key and settings.groww_api_secret:
            token=GrowwAPI.get_access_token(api_key=settings.groww_api_key,secret=settings.groww_api_secret)
        else:raise RuntimeError("Groww credentials missing")
        self.g=GrowwAPI(token)
        self.exec=GrowwExecutionClient(self.g)
    def stat(self,s):
        return {"COMPLETE":Status.FILLED,"COMPLETED":Status.FILLED,"OPEN":Status.OPEN,
          "PENDING":Status.OPEN,"REJECTED":Status.REJECTED,"CANCELLED":Status.CANCELLED}.get(
          str(s).upper(),Status.UNKNOWN)
    async def enter(self,o):
        lid=uuid.uuid4().hex[:16]
        def f():
            g=self.g;return g.place_order(trading_symbol=o.symbol,quantity=o.qty,validity=g.VALIDITY_DAY,
              exchange=g.EXCHANGE_NSE,segment=g.SEGMENT_CASH,product=g.PRODUCT_MIS,
              order_type=g.ORDER_TYPE_LIMIT,transaction_type=g.TRANSACTION_TYPE_BUY if o.action==Action.BUY
              else g.TRANSACTION_TYPE_SELL,price=o.entry,order_reference_id=("AI-"+lid)[:20])
        r=await groww_limits.call(groww_limits.order,f)
        return BrokerOrder(local_id=lid,broker_id=r.get("groww_order_id"),symbol=o.symbol,action=o.action,
          qty=o.qty,requested_price=o.entry,status=self.stat(r.get("order_status")),
          message=r.get("remark",""),updated_at=datetime.now(settings.tz))
    async def get_order(self,bid,lid):
        def f():
            if hasattr(self.g,"get_order_detail"):
                return self.g.get_order_detail(segment=self.g.SEGMENT_CASH,groww_order_id=bid)
            raise RuntimeError("Verify installed Groww SDK order-detail method")
        d=await groww_limits.call(groww_limits.live,f);d=d.get("order_detail",d)
        return BrokerOrder(local_id=lid,broker_id=bid,symbol=d.get("trading_symbol","UNKNOWN"),
          action=Action(d.get("transaction_type","HOLD")),qty=int(d.get("quantity",0)),
          filled_qty=int(d.get("filled_quantity",0)),requested_price=float(d.get("price",1) or 1),
          avg_price=float(d["average_price"]) if d.get("average_price") else None,
          status=self.stat(d.get("order_status")),message=d.get("remark",""),
          updated_at=datetime.now(settings.tz))
    async def positions(self):
        # Field names follow the same "trading_symbol"/"quantity" convention the SDK
        # already uses for orders; average-price field is unconfirmed against a real
        # account response and must be checked with the read-only probe before LIVE use.
        raw=await self.exec.positions();out=[]
        for x in raw:
            qty=int(x.get("quantity",0) or 0)
            if qty==0:continue
            avg=x.get("average_price",x.get("net_price",x.get("buy_price")))
            if avg is None:raise RuntimeError(f"Groww position missing average-price field; got keys {sorted(x)}")
            out.append(Position(symbol=x.get("trading_symbol","UNKNOWN"),qty=abs(qty),
              side=Action.BUY if qty>0 else Action.SELL,avg_price=float(avg),stop=0.0,target=0.0,
              opened_at=datetime.now(settings.tz)))
        return out
    def _to_broker_order(self,rec,fallback_price):
        return BrokerOrder(local_id=rec.reference_id,broker_id=rec.broker_order_id,symbol=rec.symbol,
          action=Action(rec.side),qty=rec.requested_qty,filled_qty=rec.filled_qty,
          requested_price=fallback_price,avg_price=rec.average_price,status=exec_status(rec.state),
          message=rec.remark,updated_at=rec.updated_at)
    async def exit(self,p,price,reason):
        # If a broker-side protective stop is resting on this position, resolve it first
        # so we never have both the native stop and a market exit live at once.
        if p.stop_order_id:
            chk=ExecutionRecord(reference_id="chk-"+uuid.uuid4().hex[:8],symbol=p.symbol,
              side=(Action.SELL if p.side==Action.BUY else Action.BUY).value,requested_qty=p.qty,
              broker_order_id=p.stop_order_id,updated_at=datetime.now(settings.tz))
            chk=await self.exec.status(chk)
            if chk.state==ExecutionState.FILLED:return self._to_broker_order(chk,price)
            await self.exec.cancel(chk)
        raw={"trading_symbol":p.symbol,"quantity":p.qty if p.side==Action.BUY else -p.qty}
        rec=await self.exec.wait_final(await self.exec.place_market_exit(raw))
        return self._to_broker_order(rec,price)
    async def place_protective_stop(self,p):
        if not settings.live_require_broker_stop:return None
        rec=await self.exec.place_stop_loss(p.symbol,p.qty,p.side,p.stop)
        return rec.broker_order_id
