import asyncio,json
from app.settings import settings
from app.broker import GrowwBroker
from app.groww_execution import GrowwExecutionClient
async def main():
    settings.validate_live();b=GrowwBroker();c=GrowwExecutionClient(b.g)
    out={"margin":await c.available_margin(),"positions":await c.positions(),
      "quote":b.g.get_quote(exchange=b.g.EXCHANGE_NSE,segment=b.g.SEGMENT_CASH,
                            trading_symbol=settings.live_probe_symbol),
      "order_test_enabled":settings.live_probe_enable_order_test}
    print(json.dumps(out,indent=2,default=str))
if __name__=="__main__":asyncio.run(main())
