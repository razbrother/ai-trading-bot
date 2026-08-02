import asyncio,time
from datetime import datetime
from urllib.parse import urlparse
import httpx
from app.settings import settings
from app.context_data import DataProvenance,NewsContext,NewsItem

class GDELTNewsProvider:
    ENDPOINT="https://api.gdeltproject.org/api/v2/doc/doc"
    def __init__(self):
        self.cache={};self.last_request=0.0;self.lock=asyncio.Lock()
    def term(self,symbol):return settings.news_term_map.get(symbol.upper(),symbol.upper())
    async def fetch(self,symbol):
        async with self.lock:
            wait=settings.gdelt_min_request_interval_seconds-(time.monotonic()-self.last_request)
            if wait>0:await asyncio.sleep(wait)
            params={"query":f'"{self.term(symbol)}"',"mode":"artlist","format":"json",
                    "sort":"datedesc","timespan":settings.gdelt_timespan,
                    "maxrecords":settings.gdelt_max_records}
            async with httpx.AsyncClient(timeout=settings.gdelt_timeout_seconds,follow_redirects=True) as c:
                r=await c.get(self.ENDPOINT,params=params)
            self.last_request=time.monotonic()
        if r.status_code!=200 or "json" not in r.headers.get("content-type","").lower():
            raise RuntimeError(f"GDELT throttled/unavailable: {r.status_code} {r.text[:120]}")
        items=[]
        for a in r.json().get("articles",[]):
            seen=a.get("seendate")
            try:published=datetime.strptime(seen,"%Y%m%dT%H%M%SZ").replace(tzinfo=settings.tz)
            except Exception:published=datetime.now(settings.tz)
            url=a.get("url");domain=a.get("domain") or (urlparse(url).netloc if url else "unknown")
            items.append(NewsItem(symbol=symbol,headline=a.get("title","")[:500],
                published_at=published,source_name=domain,source_url=url,
                sentiment="UNKNOWN",relevance=.5))
        return NewsContext(items=items,risk="UNKNOWN",provenance=DataProvenance(
            source="GDELT_DOC_2",observed_at=datetime.now(settings.tz),
            is_simulated=False,is_verified=bool(items),
            details=f"Free/open GDELT headlines: {len(items)}"))
    async def get(self,symbol):
        key=symbol.upper();x=self.cache.get(key)
        if x and time.monotonic()-x[0]<settings.gdelt_cache_seconds:return x[1]
        try:ctx=await self.fetch(key)
        except Exception as e:
            ctx=NewsContext(items=[],risk="UNKNOWN",provenance=DataProvenance(
                source="GDELT_DOC_2",observed_at=datetime.now(settings.tz),
                is_simulated=False,is_verified=False,details=str(e)))
        self.cache[key]=(time.monotonic(),ctx);return ctx
