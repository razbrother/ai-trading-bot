import asyncio,json
from pydantic import BaseModel,Field,model_validator
from app.settings import settings
from app.models import Decision,Action
from app.rate_limit import DailyCallLimiter
RULES='Use only supplied verified JSON. Select one candidate or HOLD. Do not invent prices/news/history. For BUY stop<entry<target; SELL target<entry<stop. Confidence is not probability. Never set quantity or override controls.'
class Selection(BaseModel):
    decision:Decision;selected_rank:int|None=Field(default=None,ge=1)
    @model_validator(mode='after')
    def v(self):
        if self.decision.action!=Action.HOLD and self.selected_rank is None:raise ValueError('rank required')
        return self
class HeuristicAI:
    def __init__(self,name='h'):self.name=name
    async def select(self,cs,ctx):
        if not cs or cs[0].score<settings.min_technical_score:return Selection(decision=Decision(action='HOLD',symbol=cs[0].snapshot.symbol if cs else 'NONE',confidence=.4))
        c=cs[0];s=c.snapshot
        return Selection(selected_rank=1,decision=Decision(action='BUY',symbol=s.symbol,entry=s.ltp,stop=round(s.ltp-s.atr,2),target=round(s.ltp+1.8*s.atr,2),confidence=.86,reasons=c.reasons,rationale=self.name))
class GeminiAI:
    def __init__(self):self.limiter=DailyCallLimiter(settings.gemini_max_calls_per_day,settings.tz)
    async def select(self,cs,ctx):
        await self.limiter.acquire('Gemini')
        from google import genai
        client=genai.Client(api_key=settings.gemini_api_key);payload={'candidates':[c.model_dump(mode='json') for c in cs],'context':ctx}
        def f():
            x=client.interactions.create(model=settings.gemini_model,input=RULES+'\n'+json.dumps(payload,default=str),response_format={'type':'text','mime_type':'application/json','schema':Selection.model_json_schema()});return Selection.model_validate_json(x.output_text)
        return await asyncio.to_thread(f)
class OpenAITrader:
    def __init__(self):self.limiter=DailyCallLimiter(settings.openai_max_calls_per_day,settings.tz)
    async def select(self,cs,ctx):
        await self.limiter.acquire('OpenAI')
        from openai import OpenAI
        client=OpenAI(api_key=settings.openai_api_key);payload={'candidates':[c.model_dump(mode='json') for c in cs],'context':ctx}
        def f():
            x=client.responses.parse(model=settings.openai_model,instructions=RULES,input=json.dumps(payload,default=str),text_format=Selection)
            if x.output_parsed is None:raise RuntimeError('no parsed selection')
            return x.output_parsed
        return await asyncio.to_thread(f)
class Result:
    def __init__(self,approved,final,g,o,score,reasons,candidate=None):self.approved=approved;self.final=final;self.gemini=g;self.openai=o;self.score=score;self.reasons=reasons;self.candidate=candidate
class DualConsensus:
    def __init__(self,g,o):self.g=g;self.o=o
    async def _call(self,provider,cs,ctx):
        if hasattr(provider,'select'):
            return await provider.select(cs,ctx)
        # Backward-compatible test/provider interface.
        c=cs[0]
        d=await provider.decide(c,ctx)
        return Selection(decision=d,selected_rank=1 if d.action!=Action.HOLD else None)
    async def run(self,cs,ctx):
        if not isinstance(cs,list): cs=[cs]
        gs,os=await asyncio.gather(self._call(self.g,cs,ctx),self._call(self.o,cs,ctx));g,o=gs.decision,os.decision;reasons=[];score=0;cmap={c.snapshot.symbol:c for c in cs}
        if g.action==Action.HOLD or o.action==Action.HOLD:return Result(False,None,g,o,0,['HOLD'])
        if g.symbol==o.symbol and g.symbol in cmap:score+=25
        else:reasons.append('SYMBOL_MISMATCH')
        if g.action==o.action:score+=30
        else:reasons.append('ACTION_MISMATCH')
        c=cmap.get(g.symbol) if g.symbol==o.symbol else None
        if not c:return Result(False,None,g,o,score,reasons)
        s=c.snapshot;ed=abs(g.entry-o.entry)/s.ltp*100;sd=abs(g.stop-o.stop)/s.atr;td=abs(g.target-o.target)/s.atr
        score+=15 if ed<=settings.ai_max_entry_diff_pct else 0;score+=15 if sd<=settings.ai_max_stop_diff_atr else 0;score+=15 if td<=settings.ai_max_target_diff_atr else 0
        th=settings.ai_first_trade_min_confidence if int(ctx.get('trades_today',0))==0 else settings.ai_min_confidence
        ok=g.action==o.action and g.symbol==o.symbol and score>=settings.ai_min_agreement_score and min(g.confidence,o.confidence)>=th
        if not ok:return Result(False,None,g,o,score,reasons,c)
        stop=min(g.stop,o.stop) if g.action==Action.BUY else max(g.stop,o.stop);target=min(g.target,o.target) if g.action==Action.BUY else max(g.target,o.target)
        f=Decision(action=g.action,symbol=g.symbol,entry=s.ltp,stop=stop,target=target,confidence=min(g.confidence,o.confidence),reasons=sorted(set(g.reasons+o.reasons)),rationale=f'dual agreement {score}')
        return Result(True,f,g,o,score,reasons,c)
