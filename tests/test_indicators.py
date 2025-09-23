import pandas as pd
from src.indicators.ema import ema
from src.indicators.rsi import rsi_wilder
from src.indicators.atr import atr_wilder
from src.indicators.adx import adx

def test_ema_basic():
    s = pd.Series([1,2,3,4,5,6,7,8,9,10], dtype=float)
    e = ema(s, 3)
    assert len(e) == len(s)
    assert e.iloc[-1] > e.iloc[0]

def test_rsi_range():
    s = pd.Series([1,2,3,2,3,4,5,6,7,8], dtype=float)
    r = rsi_wilder(s, 14)
    assert r.min() >= 0 - 1e-6 and r.max() <= 100 + 1e-6

def test_atr_positive():
    h = pd.Series([2,3,4,5,6], dtype=float)
    l = pd.Series([1,2,3,4,5], dtype=float)
    c = pd.Series([1.5,2.5,3.5,4.5,5.5], dtype=float)
    a = atr_wilder(h,l,c,14)
    assert (a >= 0).all()

def test_adx_shapes():
    h = pd.Series([2,3,4,5,6,7,8,9,10,11], dtype=float)
    l = pd.Series([1,2,3,4,5,6,7,8,9,10], dtype=float)
    c = pd.Series([1.5,2.5,3.5,4.5,5.5,6.5,7.5,8.5,9.5,10.5], dtype=float)
    a, pdm, mdm = adx(h,l,c,14)
    assert len(a) == len(h)
