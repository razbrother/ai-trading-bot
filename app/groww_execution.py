import asyncio,time,uuid
from dataclasses import dataclass
from datetime import datetime
from app.settings import settings
from app.execution_state import ExecutionRecord,ExecutionState
from app.models import Action,ValidOrder
from app import groww_limits

STATUS_MAP={"NEW":ExecutionState.SUBMITTED,"ACKED":ExecutionState.ACKED,
"TRIGGER_PENDING":ExecutionState.OPEN,"APPROVED":ExecutionState.OPEN,"OPEN":ExecutionState.OPEN,
"PENDING":ExecutionState.OPEN,"CANCELLATION_REQUESTED":ExecutionState.CANCEL_REQUESTED,
"CANCELLED":ExecutionState.CANCELLED,"REJECTED":ExecutionState.REJECTED,
"FAILED":ExecutionState.FAILED,"EXECUTED":ExecutionState.FILLED,
"COMPLETED":ExecutionState.FILLED,"DELIVERY_AWAITED":ExecutionState.FILLED}
def map_status(v):return STATUS_MAP.get(str(v or "").upper(),ExecutionState.UNKNOWN)
def average_trade_price(xs):
    q=sum(int(x.get("quantity",0) or 0) for x in xs)
    return (0,None) if q<=0 else (q,sum(float(x.get("price",0) or 0)*int(x.get("quantity",0) or 0) for x in xs)/q)

@dataclass
class MarginSnapshot:
    clear_cash:float;mis_available:float;cnc_available:float;total_requirement:float;charges:float

class GrowwExecutionClient:
    def __init__(self,api):self.api=api
    async def available_margin(self):return await groww_limits.call(groww_limits.nontrading,self.api.get_available_margin_details)
    async def required_margin(self,o:ValidOrder):
        g=self.api;orders=[{"trading_symbol":o.symbol,
          "transaction_type":g.TRANSACTION_TYPE_BUY if o.action==Action.BUY else g.TRANSACTION_TYPE_SELL,
          "quantity":o.qty,"price":o.entry,"order_type":g.ORDER_TYPE_LIMIT,
          "product":g.PRODUCT_MIS,"exchange":g.EXCHANGE_NSE}]
        return await groww_limits.call(groww_limits.nontrading,g.get_order_margin_details,segment=g.SEGMENT_CASH,orders=orders)
    async def assert_margin(self,o):
        a,r=await asyncio.gather(self.available_margin(),self.required_margin(o))
        e=a.get("equity_margin_details",{})
        x=MarginSnapshot(float(a.get("clear_cash",0) or 0),float(e.get("mis_balance_available",0) or 0),
          float(e.get("cnc_balance_available",0) or 0),float(r.get("total_requirement",0) or 0),
          float(r.get("brokerage_and_charges",0) or 0))
        if x.mis_available<x.total_requirement:raise RuntimeError("Insufficient MIS margin")
        return x
    async def resolve_by_reference(self,ref,symbol,side,qty):
        raw=await groww_limits.call(groww_limits.live,self.api.get_order_status_by_reference,
          order_reference_id=ref,segment=self.api.SEGMENT_CASH)
        return ExecutionRecord(reference_id=ref,symbol=symbol,side=side,requested_qty=qty,
          broker_order_id=raw.get("groww_order_id"),filled_qty=int(raw.get("filled_quantity",0) or 0),
          state=map_status(raw.get("order_status")),remark=raw.get("remark",""),
          updated_at=datetime.now(settings.tz))
    async def place_entry(self,o):
        if o.qty>settings.live_order_max_qty:raise RuntimeError("Live verification quantity cap exceeded")
        if settings.live_require_margin_check:await self.assert_margin(o)
        ref=("AI-"+uuid.uuid4().hex[:16])[:20];g=self.api
        def call():
            return g.place_order(trading_symbol=o.symbol,quantity=o.qty,validity=g.VALIDITY_DAY,
              exchange=g.EXCHANGE_NSE,segment=g.SEGMENT_CASH,product=g.PRODUCT_MIS,
              order_type=g.ORDER_TYPE_LIMIT,
              transaction_type=g.TRANSACTION_TYPE_BUY if o.action==Action.BUY else g.TRANSACTION_TYPE_SELL,
              price=o.entry,order_reference_id=ref)
        try:raw=await groww_limits.call(groww_limits.order,call)
        except Exception:return await self.resolve_by_reference(ref,o.symbol,o.action.value,o.qty)
        return ExecutionRecord(reference_id=ref,symbol=o.symbol,side=o.action.value,requested_qty=o.qty,
          broker_order_id=raw.get("groww_order_id"),state=map_status(raw.get("order_status")),
          remark=raw.get("remark",""),updated_at=datetime.now(settings.tz))
    async def status(self,r):
        if not r.broker_order_id:return await self.resolve_by_reference(r.reference_id,r.symbol,r.side,r.requested_qty)
        raw=await groww_limits.call(groww_limits.live,self.api.get_order_status,groww_order_id=r.broker_order_id,
                                    segment=self.api.SEGMENT_CASH)
        filled=int(raw.get("filled_quantity",0) or 0);state=map_status(raw.get("order_status"));avg=None
        if 0<filled<r.requested_qty:state=ExecutionState.PARTIAL
        if filled:
            t=await groww_limits.call(groww_limits.live,self.api.get_trade_list_for_order,groww_order_id=r.broker_order_id,
              segment=self.api.SEGMENT_CASH,page=0,page_size=50)
            _,avg=average_trade_price(t.get("trade_list",[]))
        return r.model_copy(update={"filled_qty":filled,"state":state,"average_price":avg,
          "remark":raw.get("remark",""),"updated_at":datetime.now(settings.tz)})
    async def cancel(self,r):
        if not r.broker_order_id:return await self.status(r)
        raw=await groww_limits.call(groww_limits.order,self.api.cancel_order,segment=self.api.SEGMENT_CASH,
                                    groww_order_id=r.broker_order_id)
        return r.model_copy(update={"state":map_status(raw.get("order_status")),
                                    "updated_at":datetime.now(settings.tz)})
    async def wait_final(self,r):
        deadline=time.monotonic()+settings.live_order_timeout_seconds;cur=r
        while time.monotonic()<deadline:
            cur=await self.status(cur)
            if cur.state in {ExecutionState.FILLED,ExecutionState.REJECTED,ExecutionState.FAILED,ExecutionState.CANCELLED}:return cur
            if cur.state==ExecutionState.PARTIAL:
                cur=await self.cancel(cur);return await self.status(cur)
            await asyncio.sleep(settings.live_order_poll_seconds)
        if settings.live_cancel_on_timeout:
            cur=await self.cancel(cur);cur=await self.status(cur)
        if cur.state not in {ExecutionState.FILLED,ExecutionState.REJECTED,ExecutionState.FAILED,ExecutionState.CANCELLED}:
            cur=cur.model_copy(update={"state":ExecutionState.UNKNOWN,"remark":"Unresolved after timeout"})
        return cur
    async def positions(self):
        raw=await groww_limits.call(groww_limits.nontrading,self.api.get_positions_for_user,segment=self.api.SEGMENT_CASH)
        return raw.get("positions",[])
    async def place_market_exit(self,p):
        q=abs(int(p.get("quantity",0) or 0))
        if not q:raise RuntimeError("Already flat")
        ref=("EX-"+uuid.uuid4().hex[:16])[:20];g=self.api;is_long=int(p["quantity"])>0
        raw=await groww_limits.call(groww_limits.order,g.place_order,trading_symbol=p["trading_symbol"],quantity=q,
          validity=g.VALIDITY_DAY,exchange=g.EXCHANGE_NSE,segment=g.SEGMENT_CASH,product=g.PRODUCT_MIS,
          order_type=g.ORDER_TYPE_MARKET,
          transaction_type=g.TRANSACTION_TYPE_SELL if is_long else g.TRANSACTION_TYPE_BUY,
          order_reference_id=ref)
        return ExecutionRecord(reference_id=ref,symbol=p["trading_symbol"],
          side="SELL" if is_long else "BUY",requested_qty=q,broker_order_id=raw.get("groww_order_id"),
          state=map_status(raw.get("order_status")),remark=raw.get("remark",""),
          updated_at=datetime.now(settings.tz))
    async def place_stop_loss(self,symbol,qty,position_side,trigger,limit_price=None):
        ref=("SL-"+uuid.uuid4().hex[:16])[:20];g=self.api
        kwargs={"trading_symbol":symbol,"quantity":qty,"validity":g.VALIDITY_DAY,
          "exchange":g.EXCHANGE_NSE,"segment":g.SEGMENT_CASH,"product":g.PRODUCT_MIS,
          "order_type":g.ORDER_TYPE_STOP_LOSS_MARKET if limit_price is None else g.ORDER_TYPE_STOP_LOSS,
          "transaction_type":g.TRANSACTION_TYPE_SELL if position_side==Action.BUY else g.TRANSACTION_TYPE_BUY,
          "trigger_price":trigger,"order_reference_id":ref}
        if limit_price is not None:kwargs["price"]=limit_price
        raw=await groww_limits.call(groww_limits.order,g.place_order,**kwargs)
        return ExecutionRecord(reference_id=ref,symbol=symbol,
          side="SELL" if position_side==Action.BUY else "BUY",requested_qty=qty,
          broker_order_id=raw.get("groww_order_id"),state=map_status(raw.get("order_status")),
          remark=raw.get("remark",""),updated_at=datetime.now(settings.tz))
