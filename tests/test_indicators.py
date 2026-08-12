from datetime import date
import pytest
from app import indicators as ind

def test_ema_matches_hand_computation():
    # closes 1..10, period 3: k=0.5, seed=SMA(1,2,3)=2, then lags a linearly
    # increasing-by-1 series by exactly 1 once warmed up.
    closes=[float(x) for x in range(1,11)]
    assert ind.ema(closes,3)==pytest.approx(9.0)

def test_ema_insufficient_data_returns_none():
    assert ind.ema([1.0,2.0],5) is None

def test_rsi_all_gains_is_100():
    closes=[float(x) for x in range(1,25)]
    assert ind.rsi(closes,period=14)==pytest.approx(100.0)

def test_rsi_all_losses_is_0():
    closes=[float(x) for x in range(24,0,-1)]
    assert ind.rsi(closes,period=14)==pytest.approx(0.0)

def test_atr_constant_true_range():
    # h-l always 2, closes stay inside next candle's h/l so TR is always exactly 2.
    candles=[(100.0,101.0,99.0,100.0)]*20
    assert ind.atr(candles,period=14)==pytest.approx(2.0)

def test_vwap_hand_computed():
    d=date(2026,8,12)
    # typical prices: (101+99+100)/3=100, (103+101+102)/3=102
    rows=[(d,101.0,99.0,100.0,10.0),(d,103.0,101.0,102.0,30.0)]
    expected=(100*10+102*30)/40
    assert ind.vwap_today(rows,d)==pytest.approx(expected)

def test_vwap_ignores_other_days():
    d=date(2026,8,12);prev=date(2026,8,11)
    rows=[(prev,200.0,198.0,199.0,999.0),(d,101.0,99.0,100.0,10.0)]
    assert ind.vwap_today(rows,d)==pytest.approx(100.0)

def test_volume_ratio_surge():
    volumes=[10.0]*20+[30.0]
    assert ind.volume_ratio(volumes)==pytest.approx(3.0)

def test_volume_ratio_insufficient_data():
    assert ind.volume_ratio([10.0]) is None

def test_compute_requires_minimum_rows():
    assert ind.compute([{"date":date(2026,8,12),"open":1,"high":1,"low":1,"close":1,"volume":1}],date(2026,8,12)) is None

def test_compute_returns_all_fields_with_enough_data():
    d=date(2026,8,12)
    rows=[{"date":d,"open":100.0+i,"high":101.0+i,"low":99.0+i,"close":100.0+i,"volume":1000.0} for i in range(30)]
    out=ind.compute(rows,d)
    assert out is not None
    assert set(out)=={"ema9","ema21","rsi","atr","vwap","volume_ratio"}
    assert all(isinstance(v,float) for v in out.values())
