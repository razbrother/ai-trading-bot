import asyncio,json,logging
from pydantic import BaseModel,Field,model_validator
from app.settings import settings
from app.models import Decision,Action
from app.rate_limit import DailyCallLimiter
RULES=('Use only supplied verified JSON. Select one candidate or HOLD. Do not invent prices/news/history. '
  'For BUY stop<entry<target; SELL target<entry<stop. Confidence is not probability. Never set quantity or '
  'override controls. If action is BUY or SELL, selected_rank is REQUIRED: set it to the 1-based position '
  '(1, 2, 3...) of the chosen candidate in the supplied candidates list. Only leave selected_rank null when action is HOLD.')
class Selection(BaseModel):
    decision:Decision
    selected_rank:int|None=Field(default=None,ge=1,
      description='Required (1-based position in candidates) when decision.action is BUY or SELL. Null only for HOLD.')
    @model_validator(mode='after')
    def v(self):
        if self.decision.action!=Action.HOLD and self.selected_rank is None:raise ValueError('rank required')
        return self
async def _select_with_retry(call_once,cs,provider_name):
    # Structured-output LLM calls occasionally return truncated/degenerate JSON
    # (e.g. a token-repetition loop cut off before the object closes) rather than
    # a clean provider error. A couple of retries clears most of these; if it
    # still fails, degrade to a safe HOLD instead of crashing the scan/pick or
    # surfacing a raw parser traceback as the trade decision.
    last_err=None
    for attempt in range(settings.ai_parse_retry_attempts):
        try:return await asyncio.to_thread(call_once)
        except Exception as e:
            last_err=e
            logging.warning("%s response failed to parse (attempt %d/%d): %s",
              provider_name,attempt+1,settings.ai_parse_retry_attempts,e)
    symbol=cs[0].snapshot.symbol if cs else 'NONE'
    return Selection(decision=Decision(action='HOLD',symbol=symbol,confidence=0,
      rationale=f'{provider_name} response unparseable after {settings.ai_parse_retry_attempts} attempts: {last_err}'))
class HeuristicAI:
    def __init__(self,name='h'):self.name=name
    async def select(self,cs,ctx):
        if not cs or cs[0].score<settings.min_technical_score:return Selection(decision=Decision(action='HOLD',symbol=cs[0].snapshot.symbol if cs else 'NONE',confidence=.4))
        c=cs[0];s=c.snapshot
        return Selection(selected_rank=1,decision=Decision(action='BUY',symbol=s.symbol,entry=s.ltp,stop=round(s.ltp-s.atr,2),target=round(s.ltp+1.8*s.atr,2),confidence=.86,reasons=c.reasons,rationale=self.name))
class GeminiAI:
    def __init__(self,notify=None):self.limiter=DailyCallLimiter(settings.gemini_max_calls_per_day,settings.tz,notify,settings.ai_budget_warn_at)
    async def select(self,cs,ctx):
        await self.limiter.acquire('Gemini')
        from google import genai
        client=genai.Client(api_key=settings.gemini_api_key);payload={'candidates':[c.model_dump(mode='json') for c in cs],'context':ctx}
        def f():
            x=client.interactions.create(model=settings.gemini_model,input=RULES+'\n'+json.dumps(payload,default=str),response_format={'type':'text','mime_type':'application/json','schema':Selection.model_json_schema()});return Selection.model_validate_json(x.output_text)
        return await _select_with_retry(f,cs,'Gemini')
class OpenAITrader:
    def __init__(self,notify=None):self.limiter=DailyCallLimiter(settings.openai_max_calls_per_day,settings.tz,notify,settings.ai_budget_warn_at)
    async def select(self,cs,ctx):
        await self.limiter.acquire('OpenAI')
        from openai import OpenAI
        client=OpenAI(api_key=settings.openai_api_key);payload={'candidates':[c.model_dump(mode='json') for c in cs],'context':ctx}
        def f():
            x=client.responses.parse(model=settings.openai_model,instructions=RULES,input=json.dumps(payload,default=str),text_format=Selection)
            if x.output_parsed is None:raise RuntimeError('no parsed selection')
            return x.output_parsed
        return await _select_with_retry(f,cs,'OpenAI')
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
        gs=await self._call(self.g,cs,ctx)
        try:os=await self._call(self.o,cs,ctx)
        except Exception:
            logging.warning("secondary AI provider failed; falling back to Gemini-only for this cycle",exc_info=True)
            os=gs
        g,o=gs.decision,os.decision;reasons=[];score=0;cmap={c.snapshot.symbol:c for c in cs}
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
ASK_RULES=('Answer the question using only the supplied JSON context about this trading bot '
  'account. Be concise and factual. Never invent numbers, positions, or trades not present in '
  'the context. If the context does not contain enough information to answer, say so plainly.')
class PortfolioAssistant:
    """Free-form Q&A over the bot's own state (positions, P&L, recent decisions) - a
    separate, smaller daily budget from the trading-decision AI calls, since casual
    questions shouldn't eat into the budget that gates actual trades."""
    def __init__(self,notify=None):self.limiter=DailyCallLimiter(settings.ask_max_calls_per_day,settings.tz,notify,settings.ai_budget_warn_at)
    async def answer(self,question,context):
        if not settings.gemini_api_key:return "GEMINI_API_KEY not configured; /ask is unavailable."
        await self.limiter.acquire('PortfolioAsk')
        from google import genai
        client=genai.Client(api_key=settings.gemini_api_key)
        prompt=f"{ASK_RULES}\n{json.dumps(context,default=str)}\n\nQuestion: {question}"
        def f():
            x=client.interactions.create(model=settings.gemini_model,input=prompt);return x.output_text
        return await asyncio.to_thread(f)
