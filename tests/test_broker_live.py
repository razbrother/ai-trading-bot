import pytest
from datetime import datetime
from app.broker import GrowwBroker
from app.groww_execution import GrowwExecutionClient
from app.models import Action,Position
from app.settings import settings

class Fake:
    SEGMENT_CASH="CASH";EXCHANGE_NSE="NSE";PRODUCT_MIS="MIS";VALIDITY_DAY="DAY"
    ORDER_TYPE_LIMIT="LIMIT";ORDER_TYPE_MARKET="MARKET";ORDER_TYPE_STOP_LOSS="SL"
    ORDER_TYPE_STOP_LOSS_MARKET="SL-M";TRANSACTION_TYPE_BUY="BUY";TRANSACTION_TYPE_SELL="SELL"
    def __init__(self):self.cancelled=[]
    def get_positions_for_user(self,segment=None):
        return {"positions":[{"trading_symbol":"WIPRO","quantity":2,"average_price":101.5}]}
    def place_order(self,**k):return {"groww_order_id":"EX1","order_status":"EXECUTED"}
    def get_order_status(self,**k):
        return {"groww_order_id":k.get("groww_order_id"),"order_status":"EXECUTED","filled_quantity":2}
    def get_trade_list_for_order(self,**k):return {"trade_list":[{"price":102,"quantity":2}]}
    def cancel_order(self,**k):
        self.cancelled.append(k.get("groww_order_id"))
        return {"groww_order_id":k.get("groww_order_id"),"order_status":"CANCELLED"}

def make_broker():
    b=GrowwBroker.__new__(GrowwBroker)
    b.g=Fake();b.exec=GrowwExecutionClient(b.g)
    return b

def pos(**kw):
    base=dict(symbol="WIPRO",qty=2,side=Action.BUY,avg_price=100,stop=98,target=104,
      opened_at=datetime.now(settings.tz))
    base.update(kw);return Position(**base)

@pytest.mark.asyncio
async def test_positions_mapping():
    b=make_broker();out=await b.positions()
    assert len(out)==1
    assert out[0].symbol=="WIPRO" and out[0].qty==2 and out[0].side==Action.BUY and out[0].avg_price==101.5

@pytest.mark.asyncio
async def test_positions_missing_avg_price_raises():
    b=make_broker()
    b.g.get_positions_for_user=lambda segment=None:{"positions":[{"trading_symbol":"WIPRO","quantity":1}]}
    with pytest.raises(RuntimeError):
        await b.positions()

@pytest.mark.asyncio
async def test_exit_without_stop_order_places_market_exit():
    b=make_broker()
    x=await b.exit(pos(),102,"TARGET")
    assert x.status.value=="FILLED" and x.broker_id=="EX1"

@pytest.mark.asyncio
async def test_exit_cancels_resting_stop_before_market_exit():
    b=make_broker()
    def status(**k):
        if k.get("groww_order_id")=="SL1":return {"order_status":"TRIGGER_PENDING","filled_quantity":0}
        return {"groww_order_id":k.get("groww_order_id"),"order_status":"EXECUTED","filled_quantity":2}
    b.g.get_order_status=status
    x=await b.exit(pos(stop_order_id="SL1"),104,"TARGET")
    assert "SL1" in b.g.cancelled
    assert x.broker_id=="EX1" and x.status.value=="FILLED"

@pytest.mark.asyncio
async def test_exit_uses_already_filled_stop_order_without_double_exit():
    b=make_broker()
    x=await b.exit(pos(stop_order_id="SL1"),98,"STOP")
    assert x.broker_id=="SL1" and x.status.value=="FILLED"
    assert not b.g.cancelled

@pytest.mark.asyncio
async def test_place_protective_stop_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(settings,"live_require_broker_stop",False)
    b=make_broker()
    assert await b.place_protective_stop(pos()) is None

@pytest.mark.asyncio
async def test_place_protective_stop_enabled_places_order(monkeypatch):
    monkeypatch.setattr(settings,"live_require_broker_stop",True)
    b=make_broker()
    b.g.get_order_status=lambda **k:{"order_status":"OPEN","filled_quantity":0}
    order_id=await b.place_protective_stop(pos())
    assert order_id=="EX1"
