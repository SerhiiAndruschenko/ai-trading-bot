"""
Низькорівневий клієнт до Binance USDT-M Futures REST API.
Повертає «сирі» дані; вся бізнес-логіка — в інших модулях.
"""
from __future__ import annotations

import time
from typing import Any

from binance.client import Client
from binance.exceptions import BinanceAPIException

import config
from logger import log

# ── Ініціалізація клієнта ─────────────────────────────────────────────────────
_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(
            api_key=config.API_KEY,
            api_secret=config.API_SECRET,
            testnet=config.TESTNET,
        )
    return _client


# ── Баланс ────────────────────────────────────────────────────────────────────

def get_futures_balance() -> tuple[float, float]:
    """Повертає (available_balance, wallet_balance) у USDT."""
    try:
        assets = get_client().futures_account_balance()
        for a in assets:
            if a["asset"] == "USDT":
                return float(a["availableBalance"]), float(a["balance"])
    except BinanceAPIException as e:
        log.error(f"get_futures_balance помилка: {e}")
    return 0.0, 0.0


def get_available_balance() -> float:
    available, _ = get_futures_balance()
    return available


# ── Свічки ────────────────────────────────────────────────────────────────────

def get_klines(symbol: str, interval: str, limit: int) -> list[list]:
    """Повертає список OHLCV свічок."""
    try:
        return get_client().futures_klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
        )
    except BinanceAPIException as e:
        log.error(f"get_klines {symbol} помилка: {e}")
        return []


# ── Поточна ціна ──────────────────────────────────────────────────────────────

def get_symbol_price(symbol: str) -> float:
    try:
        t = get_client().futures_symbol_ticker(symbol=symbol)
        return float(t["price"])
    except BinanceAPIException as e:
        log.error(f"get_symbol_price {symbol} помилка: {e}")
        return 0.0


# ── Funding rate ──────────────────────────────────────────────────────────────

def get_funding_rate(symbol: str) -> float:
    """Останній funding rate у %."""
    try:
        data = get_client().futures_funding_rate(symbol=symbol, limit=1)
        if data:
            return float(data[-1]["fundingRate"]) * 100
    except BinanceAPIException as e:
        log.error(f"get_funding_rate {symbol} помилка: {e}")
    return 0.0


# ── Відкриті позиції ──────────────────────────────────────────────────────────

def get_open_positions() -> list[dict]:
    """Всі позиції з positionAmt != 0."""
    try:
        positions = get_client().futures_position_information()
        return [p for p in positions if float(p["positionAmt"]) != 0]
    except BinanceAPIException as e:
        log.error(f"get_open_positions помилка: {e}")
        return []


def get_position_for_symbol(symbol: str) -> dict | None:
    """Позиція по конкретному символу або None."""
    for p in get_open_positions():
        if p["symbol"] == symbol:
            return p
    return None


# ── Ордери ────────────────────────────────────────────────────────────────────

def set_leverage(symbol: str, leverage: int) -> None:
    try:
        get_client().futures_change_leverage(symbol=symbol, leverage=leverage)
    except BinanceAPIException as e:
        log.warning(f"set_leverage {symbol} x{leverage}: {e}")


def place_market_order(
    symbol: str,
    side: str,           # "BUY" | "SELL"
    quantity: float,
) -> dict | None:
    try:
        order = get_client().futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity,
        )
        log.info(f"Ордер {side} {quantity} {symbol}: orderId={order['orderId']}")
        return order
    except BinanceAPIException as e:
        log.error(f"place_market_order {symbol} {side} помилка: {e}")
        return None


def get_exchange_info(symbol: str) -> dict | None:
    """Інформація про символ (stepSize, tickSize тощо)."""
    try:
        info = get_client().futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                return s
    except BinanceAPIException as e:
        log.error(f"get_exchange_info {symbol} помилка: {e}")
    return None


def get_symbol_filters(symbol: str) -> dict[str, Any]:
    """Повертає dict з stepSize і minQty."""
    info = get_exchange_info(symbol)
    result = {"stepSize": "0.001", "minQty": "0.001"}
    if not info:
        return result
    for f in info.get("filters", []):
        if f["filterType"] == "LOT_SIZE":
            result["stepSize"] = f["stepSize"]
            result["minQty"]   = f["minQty"]
    return result


# ── Перевірка з'єднання ───────────────────────────────────────────────────────

def check_connection() -> bool:
    try:
        get_client().futures_ping()
        return True
    except Exception as e:
        log.error(f"Binance connection check failed: {e}")
        return False


# ── Допоміжні ─────────────────────────────────────────────────────────────────

def round_step(value: float, step: str) -> float:
    """Округлення кількості до stepSize."""
    import math
    step_f = float(step)
    if step_f == 0:
        return value
    precision = max(0, int(round(-math.log10(step_f))))
    return round(math.floor(value / step_f) * step_f, precision)
