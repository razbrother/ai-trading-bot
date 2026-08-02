import random
from datetime import datetime
from app.settings import settings
from app.models import Snapshot,Candidate

class MockMarket:
    def __init__(self,seed=42): self.r=random.Random(seed);self.prices={}
    async def snapshot(self,i):
        old=self.prices.setdefault(i.symbol,100+sum(map(ord,i.symbol))%900)
        t=self.r.uniform(-1,1);ltp=max(10,old*(1+self.r.uniform(-.004,.006)));self.prices[i.symbol]=ltp
        atr=max(.5,ltp*.008);vr=self.r.uniform(.7,2.5);sp=ltp*.0004
        return Snapshot(symbol=i.symbol,timestamp=datetime.now(settings.tz),ltp=round(ltp,2),
          open=round(old,2),high=round(max(old,ltp)+atr*.3,2),low=round(min(old,ltp)-atr*.3,2),
          volume_ratio=round(vr,2),bid=round(ltp-sp/2,2),ask=round(ltp+sp/2,2),
          vwap=round(ltp*(1-t*.0015),2),ema9=round(ltp*(1-t*.001),2),
          ema21=round(ltp*(1-t*.003),2),rsi=round(50+t*18,2),atr=round(atr,2),
          index_change=round(t*.5,2),sector_change=round(t*.7,2),news_risk="LOW",source="MOCK")
    async def snapshots(self,items): return [await self.snapshot(i) for i in items]

def score(s):
    n=0;r=[]
    if s.ema9>s.ema21:n+=20;r+=["EMA"]
    if s.ltp>s.vwap:n+=15;r+=["VWAP"]
    if 52<=s.rsi<=70:n+=15;r+=["RSI"]
    if s.volume_ratio>=1.5:n+=20;r+=["VOLUME"]
    elif s.volume_ratio>=1.1:n+=10
    if s.index_change>0:n+=10;r+=["INDEX"]
    if s.sector_change>0:n+=10;r+=["SECTOR"]
    if s.spread_pct<=settings.max_spread_pct:n+=10;r+=["SPREAD"]
    if s.news_risk=="HIGH":n=max(0,n-30)
    return Candidate(snapshot=s,score=min(n,100),reasons=r)
