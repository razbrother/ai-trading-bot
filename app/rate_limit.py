import asyncio,time
from collections import deque
from datetime import datetime
class RollingRateLimiter:
    def __init__(self,per_second,per_minute):
        self.ps=per_second;self.pm=per_minute;self.s=deque();self.m=deque();self.lock=asyncio.Lock()
    async def acquire(self):
        async with self.lock:
            while True:
                now=time.monotonic()
                while self.s and now-self.s[0]>=1:self.s.popleft()
                while self.m and now-self.m[0]>=60:self.m.popleft()
                if len(self.s)<self.ps and len(self.m)<self.pm:
                    self.s.append(now);self.m.append(now);return
                waits=[]
                if len(self.s)>=self.ps:waits.append(1-(now-self.s[0]))
                if len(self.m)>=self.pm:waits.append(60-(now-self.m[0]))
                await asyncio.sleep(max(.01,min(waits)))

class DailyCallLimiter:
    """Caps calls per local calendar day; resets automatically at day rollover."""
    def __init__(self,max_per_day,tz):
        self.max=max_per_day;self.tz=tz;self.day=None;self.count=0;self.lock=asyncio.Lock()
    async def acquire(self,label="call"):
        async with self.lock:
            today=datetime.now(self.tz).date()
            if today!=self.day:self.day=today;self.count=0
            if self.count>=self.max:raise RuntimeError(f"Daily {label} cap reached ({self.max}/day)")
            self.count+=1
