import asyncio,uuid
from datetime import datetime
from app.settings import settings
from app.models import Action,Status,BrokerOrder,Position,ValidOrder

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
        r=await asyncio.to_thread(f)
        return BrokerOrder(local_id=lid,broker_id=r.get("groww_order_id"),symbol=o.symbol,action=o.action,
          qty=o.qty,requested_price=o.entry,status=self.stat(r.get("order_status")),
          message=r.get("remark",""),updated_at=datetime.now(settings.tz))
    async def get_order(self,bid,lid):
        def f():
            if hasattr(self.g,"get_order_detail"):
                return self.g.get_order_detail(segment=self.g.SEGMENT_CASH,groww_order_id=bid)
            raise RuntimeError("Verify installed Groww SDK order-detail method")
        d=await asyncio.to_thread(f);d=d.get("order_detail",d)
        return BrokerOrder(local_id=lid,broker_id=bid,symbol=d.get("trading_symbol","UNKNOWN"),
          action=Action(d.get("transaction_type","HOLD")),qty=int(d.get("quantity",0)),
          filled_qty=int(d.get("filled_quantity",0)),requested_price=float(d.get("price",1) or 1),
          avg_price=float(d["average_price"]) if d.get("average_price") else None,
          status=self.stat(d.get("order_status")),message=d.get("remark",""),
          updated_at=datetime.now(settings.tz))
    async def positions(self):
        raise RuntimeError("Map and verify current Groww positions response before LIVE use")
    async def exit(self,p,price,reason):
        raise RuntimeError("Map and verify current Groww exit/reconciliation before LIVE use")
