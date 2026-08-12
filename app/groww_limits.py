import asyncio
from app.settings import settings
from app.rate_limit import RollingRateLimiter

# Groww enforces separate rate buckets per call category (see README "Recommended
# Groww internal targets"). One limiter per bucket, shared by every caller in the
# process so concurrent scan/monitor/reconcile ticks never exceed the account limit.
order=RollingRateLimiter(settings.groww_order_rps,settings.groww_order_rpm)
live=RollingRateLimiter(settings.groww_live_rps,settings.groww_live_rpm)
nontrading=RollingRateLimiter(settings.groww_nontrading_rps,settings.groww_nontrading_rpm)

async def call(limiter,fn,*a,**kw):
    await limiter.acquire()
    return await asyncio.to_thread(fn,*a,**kw)
