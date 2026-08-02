import asyncio,time
from collections import deque
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
