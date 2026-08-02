import pytest
from datetime import datetime
from app.groww_execution import map_status,average_trade_price,GrowwExecutionClient
from app.execution_state import ExecutionState
from app.models import ValidOrder
from app.settings import settings
def test_statuses():
    assert map_status("EXECUTED")==ExecutionState.FILLED
    assert map_status("TRIGGER_PENDING")==ExecutionState.OPEN
    assert map_status("CANCELLATION_REQUESTED")==ExecutionState.CANCEL_REQUESTED
    assert map_status("bad")==ExecutionState.UNKNOWN
def test_average():
    q,a=average_trade_price([{"price":100,"quantity":2},{"price":101,"quantity":1}])
    assert q==3 and a==pytest.approx(100.333333)
class Fake:
    SEGMENT_CASH="CASH";EXCHANGE_NSE="NSE";PRODUCT_MIS="MIS";VALIDITY_DAY="DAY"
    ORDER_TYPE_LIMIT="LIMIT";ORDER_TYPE_MARKET="MARKET";ORDER_TYPE_STOP_LOSS="SL"
    ORDER_TYPE_STOP_LOSS_MARKET="SL-M";TRANSACTION_TYPE_BUY="BUY";TRANSACTION_TYPE_SELL="SELL"
    def get_available_margin_details(self):return {"clear_cash":1000,"equity_margin_details":{"mis_balance_available":1000,"cnc_balance_available":1000}}
    def get_order_margin_details(self,segment,orders):return {"total_requirement":100,"brokerage_and_charges":1}
    def place_order(self,**k):return {"groww_order_id":"G1","order_status":"OPEN"}
    def get_order_status(self,**k):return {"groww_order_id":"G1","order_status":"EXECUTED","filled_quantity":1}
    def get_trade_list_for_order(self,**k):return {"trade_list":[{"price":100,"quantity":1}]}
    def get_positions_for_user(self,segment=None):return {"positions":[{"trading_symbol":"WIPRO","quantity":1}]}
    def cancel_order(self,**k):return {"groww_order_id":"G1","order_status":"CANCELLED"}
@pytest.mark.asyncio
async def test_lifecycle(monkeypatch):
    monkeypatch.setattr(settings,"live_order_max_qty",1)
    c=GrowwExecutionClient(Fake())
    o=ValidOrder(symbol="WIPRO",action="BUY",qty=1,entry=100,stop=99,target=102,
      risk=1,rr=2,confidence=.9,score=90,signal_time=datetime.now(settings.tz))
    r=await c.wait_final(await c.place_entry(o))
    assert r.state==ExecutionState.FILLED and r.filled_qty==1 and r.average_price==100
