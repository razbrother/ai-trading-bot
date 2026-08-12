from __future__ import annotations
from datetime import date

def ema(closes:list[float],period:int)->float|None:
    if len(closes)<period:return None
    k=2/(period+1)
    v=sum(closes[:period])/period
    for c in closes[period:]:v=c*k+v*(1-k)
    return v

def rsi(closes:list[float],period:int=14)->float|None:
    if len(closes)<period+1:return None
    gains=[max(closes[i]-closes[i-1],0) for i in range(1,period+1)]
    losses=[max(closes[i-1]-closes[i],0) for i in range(1,period+1)]
    avg_gain=sum(gains)/period;avg_loss=sum(losses)/period
    for i in range(period+1,len(closes)):
        d=closes[i]-closes[i-1]
        avg_gain=(avg_gain*(period-1)+max(d,0))/period
        avg_loss=(avg_loss*(period-1)+max(-d,0))/period
    if avg_loss==0:return 100.0
    rs=avg_gain/avg_loss
    return 100-(100/(1+rs))

def atr(candles:list[tuple[float,float,float,float]],period:int=14)->float|None:
    """candles: chronological (open,high,low,close) tuples."""
    if len(candles)<period+1:return None
    trs=[];prev_close=candles[0][3]
    for _,h,l,c in candles[1:]:
        trs.append(max(h-l,abs(h-prev_close),abs(l-prev_close)));prev_close=c
    if len(trs)<period:return None
    v=sum(trs[:period])/period
    for tr in trs[period:]:v=(v*(period-1)+tr)/period
    return v

def vwap_today(rows:list[tuple[date,float,float,float,float]],today:date)->float|None:
    """rows: (date, high, low, close, volume). Session VWAP from today's candles only."""
    num=den=0.0
    for d,h,l,c,vol in rows:
        if d!=today or not vol:continue
        num+=(h+l+c)/3*vol;den+=vol
    return num/den if den else None

def volume_ratio(volumes:list[float],lookback:int=20)->float|None:
    if len(volumes)<2:return None
    recent=volumes[-1]
    base=volumes[-(lookback+1):-1] if len(volumes)>lookback else volumes[:-1]
    avg=sum(base)/len(base) if base else 0
    if not avg:return None
    return recent/avg

def compute(rows:list[dict],today:date)->dict|None:
    """rows: chronological dicts with date/open/high/low/close/volume, already cleaned of gaps."""
    if len(rows)<22:return None
    closes=[r["close"] for r in rows]
    ema9=ema(closes,9);ema21=ema(closes,21);r=rsi(closes)
    a=atr([(x["open"],x["high"],x["low"],x["close"]) for x in rows])
    vw=vwap_today([(x["date"],x["high"],x["low"],x["close"],x["volume"]) for x in rows],today)
    vr=volume_ratio([x["volume"] for x in rows])
    if None in (ema9,ema21,r,a,vw,vr):return None
    return {"ema9":ema9,"ema21":ema21,"rsi":r,"atr":a,"vwap":vw,"volume_ratio":vr}
