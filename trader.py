"""
Торговий модуль: відкриття/закриття позицій, soft SL/TP моніторинг,
синхронізація з біржею.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import config
import binance_client as bc
from risk_manager import risk_manager
from logger import log

# Комісія тейкера
TAKER_FEE = 0.0005

# Внутрішній реєстр відкритих угод
# { symbol: { "side", "entry_price", "qty", "tp_price", "sl_price",
#             "tp_pct", "sl_pct", "opened_at", "confidence", "reason" } }
_open_trades: dict[str, dict[str, Any]] = {}


# ── Допоміжні ────────────────────────────────────────────────────────────────

def _calc_quantity(symbol: str, price: float, balance: float) -> float:
    """Розраховує кількість монет для ордеру."""
    trade_usdt = min(balance, config.MAX_TRADING_BALANCE) * config.RISK_PER_TRADE
    notional   = trade_usdt * config.LEVERAGE
    filters    = bc.get_symbol_filters(symbol)
    qty        = notional / price
    qty        = bc.round_step(qty, filters["stepSize"])
    return max(qty, float(filters["minQty"]))


def _duration_str(opened_at: datetime) -> str:
    delta = datetime.now(timezone.utc) - opened_at
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m = rem // 60
    if h:
        return f"{h}г {m}хв"
    return f"{m}хв"


# ── Відкриття позиції ─────────────────────────────────────────────────────────

def open_position(
    symbol: str,
    action: str,          # "LONG" | "SHORT"
    tp_pct: float,
    sl_pct: float,
    balance: float,
    confidence: float = 0.0,
    reason: str = "",
) -> bool:
    """
    Відкриває ринкову позицію.
    Повертає True при успіху.
    """
    if symbol in _open_trades:
        log.info(f"[{symbol}] Позиція вже відкрита — пропускаємо")
        return False

    # Перевірка глобального ліміту відкритих угод
    if len(_open_trades) >= config.MAX_OPEN_TRADES_GLOBAL:
        log.info(f"Досягнуто MAX_OPEN_TRADES_GLOBAL={config.MAX_OPEN_TRADES_GLOBAL}")
        return False

    price = bc.get_symbol_price(symbol)
    if price == 0:
        log.error(f"[{symbol}] Не вдалося отримати ціну")
        return False

    # Плече
    bc.set_leverage(symbol, config.LEVERAGE)

    qty = _calc_quantity(symbol, price, balance)
    side = "BUY" if action == "LONG" else "SELL"

    order = bc.place_market_order(symbol, side, qty)
    if not order:
        return False

    # Виконана ціна
    entry_price = float(order.get("avgPrice") or order.get("price") or price)
    if entry_price == 0:
        entry_price = price

    # TP / SL рівні
    if action == "LONG":
        tp_price = entry_price * (1 + tp_pct)
        sl_price = entry_price * (1 - sl_pct)
    else:
        tp_price = entry_price * (1 - tp_pct)
        sl_price = entry_price * (1 + sl_pct)

    _open_trades[symbol] = {
        "side":        action,
        "entry_price": entry_price,
        "qty":         qty,
        "tp_price":    tp_price,
        "sl_price":    sl_price,
        "tp_pct":      tp_pct,
        "sl_pct":      sl_pct,
        "opened_at":   datetime.now(timezone.utc),
        "confidence":  confidence,
        "reason":      reason,
    }

    log.info(
        f"[{symbol}] ВІДКРИТО {action} | qty={qty} | entry={entry_price:.4f} "
        f"TP={tp_price:.4f} (+{tp_pct*100:.2f}%) SL={sl_price:.4f} (-{sl_pct*100:.2f}%)"
    )

    # Повідомлення
    _notify_open(symbol, action, entry_price, qty, tp_price, sl_price,
                 tp_pct, sl_pct, confidence, reason)
    return True


# ── Закриття позиції ──────────────────────────────────────────────────────────

def close_position(symbol: str, reason: str = "") -> bool:
    """Закриває позицію по символу."""
    trade = _open_trades.get(symbol)
    if not trade:
        log.info(f"[{symbol}] Немає відкритої позиції для закриття")
        return False

    price = bc.get_symbol_price(symbol)
    side  = "SELL" if trade["side"] == "LONG" else "BUY"
    qty   = trade["qty"]

    order = bc.place_market_order(symbol, side, qty)
    exit_price = float(order.get("avgPrice") or order.get("price") or price) if order else price

    # P&L з урахуванням комісії
    if trade["side"] == "LONG":
        raw_pnl = (exit_price - trade["entry_price"]) * qty
    else:
        raw_pnl = (trade["entry_price"] - exit_price) * qty

    fee = trade["entry_price"] * qty * TAKER_FEE * 2
    pnl = raw_pnl - fee

    pnl_pct = (exit_price - trade["entry_price"]) / trade["entry_price"] * 100
    if trade["side"] == "SHORT":
        pnl_pct = -pnl_pct

    duration = _duration_str(trade["opened_at"])

    log.info(
        f"[{symbol}] ЗАКРИТО {trade['side']} | "
        f"entry={trade['entry_price']:.4f} exit={exit_price:.4f} "
        f"P&L={pnl:+.4f} USDT ({pnl_pct:+.2f}%) | {reason}"
    )

    # Запис P&L
    won = pnl > 0
    risk_manager.record_trade_pnl(pnl)
    risk_manager.record_trade_result(won, "daily")
    risk_manager.record_trade_result(won, "monthly")

    _notify_close(symbol, trade, exit_price, pnl, pnl_pct, duration, reason)

    del _open_trades[symbol]
    return True


def close_all_positions(reason: str = "") -> None:
    """Закриває всі відкриті позиції реєстру."""
    symbols = list(_open_trades.keys())
    if not symbols:
        # Також перевіряємо позиції на біржі (на випадок розбіжності)
        for pos in bc.get_open_positions():
            sym = pos["symbol"]
            amt = float(pos["positionAmt"])
            if amt == 0:
                continue
            side = "SELL" if amt > 0 else "BUY"
            bc.place_market_order(sym, side, abs(amt))
            log.info(f"[{sym}] Закрито позицію з біржі | {reason}")
        return

    for sym in symbols:
        close_position(sym, reason)


# ── Soft SL/TP моніторинг ─────────────────────────────────────────────────────

def check_sl_tp_all() -> None:
    """
    Перевіряє soft SL/TP для всіх відкритих позицій.
    Розраховує P&L% з урахуванням плеча.
    """
    for symbol, trade in list(_open_trades.items()):
        price = bc.get_symbol_price(symbol)
        if price == 0:
            continue

        entry = trade["entry_price"]
        side  = trade["side"]

        if side == "LONG":
            pnl_pct_leveraged = (price - entry) / entry * config.LEVERAGE * 100
            hit_tp = price >= trade["tp_price"]
            hit_sl = price <= trade["sl_price"]
        else:
            pnl_pct_leveraged = (entry - price) / entry * config.LEVERAGE * 100
            hit_tp = price <= trade["tp_price"]
            hit_sl = price >= trade["sl_price"]

        log.debug(
            f"[{symbol}] {side} | ціна={price:.4f} | "
            f"P&L(lever)={pnl_pct_leveraged:+.2f}% | "
            f"TP={trade['tp_price']:.4f} SL={trade['sl_price']:.4f}"
        )

        if hit_tp:
            log.info(f"[{symbol}] TP досягнуто ({price:.4f} >= {trade['tp_price']:.4f})")
            close_position(symbol, "TP")
        elif hit_sl:
            log.info(f"[{symbol}] SL досягнуто ({price:.4f} <= {trade['sl_price']:.4f})")
            close_position(symbol, "SL")


# ── Синхронізація з біржею ────────────────────────────────────────────────────

def reconcile_open_trades() -> None:
    """
    Звіряє внутрішній реєстр із реальними позиціями на біржі.
    Видаляє з реєстру символи, яких вже немає на біржі.
    """
    exchange_positions = {
        p["symbol"]: p
        for p in bc.get_open_positions()
        if float(p.get("positionAmt", 0)) != 0
    }

    # Видаляємо закриті
    for sym in list(_open_trades.keys()):
        if sym not in exchange_positions:
            log.warning(f"[{sym}] Позиція є в реєстрі, але відсутня на біржі — видаляємо")
            del _open_trades[sym]

    # Додаємо позиції, яких немає в реєстрі (наприклад, ручно відкриті)
    for sym, pos in exchange_positions.items():
        if sym not in _open_trades:
            amt        = float(pos["positionAmt"])
            side       = "LONG" if amt > 0 else "SHORT"
            entry      = float(pos.get("entryPrice", 0))
            update_ms  = int(pos.get("updateTime", 0))
            opened_at  = (
                datetime.fromtimestamp(update_ms / 1000, tz=timezone.utc)
                if update_ms else datetime.now(timezone.utc)
            )
            # Дефолтні TP/SL для «зовнішніх» позицій
            tp_pct = config.MIN_TAKE_PROFIT_PCT
            sl_pct = config.MIN_STOP_LOSS_PCT
            tp_price = entry * (1 + tp_pct) if side == "LONG" else entry * (1 - tp_pct)
            sl_price = entry * (1 - sl_pct) if side == "LONG" else entry * (1 + sl_pct)

            _open_trades[sym] = {
                "side":        side,
                "entry_price": entry,
                "qty":         abs(amt),
                "tp_price":    tp_price,
                "sl_price":    sl_price,
                "tp_pct":      tp_pct,
                "sl_pct":      sl_pct,
                "opened_at":   opened_at,
                "confidence":  0.0,
                "reason":      "reconciled",
            }
            log.info(f"[{sym}] Додано з біржі: {side} qty={abs(amt)} entry={entry:.4f}")

    log.info(f"reconcile: відкритих угод у реєстрі = {len(_open_trades)}")


# ── Геттери ───────────────────────────────────────────────────────────────────

def get_open_trades() -> dict[str, dict]:
    return dict(_open_trades)


def count_open_trades() -> int:
    return len(_open_trades)


# ── Повідомлення ──────────────────────────────────────────────────────────────
# (Lazy import щоб уникнути циклічного імпорту)

def _notify_open(symbol, action, entry, qty, tp, sl, tp_pct, sl_pct, confidence, reason):
    try:
        import notifications
        notifications.on_position_opened(
            symbol=symbol, action=action,
            entry_price=entry, qty=qty,
            tp_price=tp, sl_price=sl,
            tp_pct=tp_pct, sl_pct=sl_pct,
            confidence=confidence, reason=reason,
        )
    except Exception as e:
        log.warning(f"notify open error: {e}")


def _notify_close(symbol, trade, exit_price, pnl, pnl_pct, duration, reason):
    try:
        import notifications
        notifications.on_position_closed(
            symbol=symbol,
            side=trade["side"],
            entry_price=trade["entry_price"],
            exit_price=exit_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            duration=duration,
            reason=reason,
        )
    except Exception as e:
        log.warning(f"notify close error: {e}")
