"""
Data collector: market data for AI agent.
Uses 'ta' library (Python 3.10+ compatible).
"""
from __future__ import annotations

import pandas as pd
import ta as ta_lib

import config
import binance_client as bc
from logger import log


def _klines_to_df(raw: list) -> pd.DataFrame:
    df = pd.DataFrame(raw, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df.set_index("open_time")


def _price_changes(df: pd.DataFrame, current_price: float) -> dict:
    closes = df["close"].values
    n = len(closes)

    def pct(periods: int) -> float:
        idx = n - 1 - periods
        if idx < 0:
            return 0.0
        past = float(closes[idx])
        return (current_price - past) / past * 100 if past else 0.0

    # change_15m: поточна ціна vs ціна 1 свічку назад (1 × 15хв = 15 хв)
    last_close  = float(closes[-1]) if n >= 1 else 0.0
    prev_close  = float(closes[-2]) if n >= 2 else last_close
    change_15m  = (current_price - prev_close) / prev_close * 100 if prev_close else 0.0

    return {
        "change_15m": change_15m,
        "change_1h":  pct(4),
        "change_4h":  pct(16),
        "change_24h": pct(min(96, n - 1)),
    }


def _last_5_candles_str(df: pd.DataFrame) -> str:
    tail = df.tail(5)[["open", "high", "low", "close", "volume"]]
    lines = []
    for ts, row in tail.iterrows():
        line = (
            "  " + ts.strftime("%H:%M") + "  "
            + "O=" + format(float(row["open"]), ".2f")
            + " H=" + format(float(row["high"]), ".2f")
            + " L=" + format(float(row["low"]), ".2f")
            + " C=" + format(float(row["close"]), ".2f")
            + " V=" + format(float(row["volume"]), ".0f")
        )
        lines.append(line)
    return "\n".join(lines)


def _safe_float(v) -> float:
    try:
        f = float(v)
        return f if f == f else 0.0
    except Exception:
        return 0.0


def _calc_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    ema21 = ta_lib.trend.EMAIndicator(close, window=21).ema_indicator().iloc[-1]
    ema50 = ta_lib.trend.EMAIndicator(close, window=50).ema_indicator().iloc[-1]
    rsi   = ta_lib.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]

    macd_obj    = ta_lib.trend.MACD(close, window_fast=12, window_slow=26, window_sign=9)
    macd        = macd_obj.macd().iloc[-1]
    macd_signal = macd_obj.macd_signal().iloc[-1]
    macd_hist   = macd_obj.macd_diff().iloc[-1]

    atr = ta_lib.volatility.AverageTrueRange(
        high, low, close, window=14
    ).average_true_range().iloc[-1]

    return {
        "ema21":       _safe_float(ema21),
        "ema50":       _safe_float(ema50),
        "rsi":         _safe_float(rsi),
        "macd":        _safe_float(macd),
        "macd_signal": _safe_float(macd_signal),
        "macd_hist":   _safe_float(macd_hist),
        "atr":         _safe_float(atr),
    }


def collect_market_data(symbol: str) -> dict:
    """
    Returns dict with all market data for the symbol:
    price, ema21/50, rsi, macd, atr, volume, changes, funding_rate,
    open_position, last_5_candles.
    """
    raw = bc.get_klines(symbol, config.TIMEFRAME, config.CANDLES_LIMIT)
    if not raw or len(raw) < 30:
        log.warning("[%s] Not enough candles: %d", symbol, len(raw))
        return {}

    df     = _klines_to_df(raw)
    indic  = _calc_indicators(df)
    last   = df.iloc[-1]

    volume     = float(last["volume"])
    avg_volume = float(df["volume"].tail(20).mean())
    vol_ratio  = volume / avg_volume if avg_volume else 1.0

    price = bc.get_symbol_price(symbol)
    if price == 0.0:
        price = float(last["close"])

    changes       = _price_changes(df, price)
    funding_rate  = bc.get_funding_rate(symbol)
    open_position = bc.get_position_for_symbol(symbol)
    last_5        = _last_5_candles_str(df)

    data = {
        "symbol":         symbol,
        "price":          price,
        "ema21":          indic["ema21"],
        "ema50":          indic["ema50"],
        "rsi":            indic["rsi"],
        "macd":           indic["macd"],
        "macd_signal":    indic["macd_signal"],
        "macd_hist":      indic["macd_hist"],
        "atr":            indic["atr"],
        "volume":         volume,
        "avg_volume":     avg_volume,
        "vol_ratio":      vol_ratio,
        "change_15m":     changes["change_15m"],
        "change_1h":      changes["change_1h"],
        "change_4h":      changes["change_4h"],
        "change_24h":     changes["change_24h"],
        "funding_rate":   funding_rate,
        "open_position":  open_position,
        "last_5_candles": last_5,
    }

    log.debug(
        "[%s] Data collected: price=%.4f EMA21=%.4f EMA50=%.4f RSI=%.1f "
        "vol_ratio=%.2fx funding=%.4f%% 15m=%+.2f%%",
        symbol, price, indic["ema21"], indic["ema50"], indic["rsi"],
        vol_ratio, funding_rate, changes["change_15m"],
    )
    return data
