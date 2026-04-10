"""
Telegram-повідомлення для AI-бота.
Всі повідомлення мають префікс [AI].
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import config
from logger import log

# ── Lazy-імпорт Telegram ──────────────────────────────────────────────────────
_tg_app = None   # буде встановлено з telegram_bot.py


def set_app(app) -> None:
    """Реєструємо Telegram Application з telegram_bot.py."""
    global _tg_app
    _tg_app = app


def _send(text: str) -> None:
    """Надсилає повідомлення в Telegram (неблокуюче)."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.debug(f"[Notify stub] {text[:80]}")
        return

    async def _do():
        try:
            from telegram import Bot
            bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
            kwargs: dict = {
                "chat_id":    config.TELEGRAM_CHAT_ID,
                "text":       text,
                "parse_mode": "HTML",
            }
            if config.TELEGRAM_THREAD_ID:
                kwargs["message_thread_id"] = int(config.TELEGRAM_THREAD_ID)
            await bot.send_message(**kwargs)
        except Exception as e:
            log.warning(f"Telegram надсилання помилка: {e}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_do())
        else:
            loop.run_until_complete(_do())
    except Exception as e:
        log.warning(f"Telegram event loop помилка: {e}")


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")


# ── Відкриття позиції ─────────────────────────────────────────────────────────

def on_position_opened(
    symbol: str,
    action: str,          # "LONG" | "SHORT"
    entry_price: float,
    qty: float,
    tp_price: float,
    sl_price: float,
    tp_pct: float,
    sl_pct: float,
    confidence: float,
    reason: str,
) -> None:
    icon = "🟢" if action == "LONG" else "🔴"
    notional = round(entry_price * qty, 2)
    conf_pct = int(confidence * 100)

    text = (
        f"<b>{config.BOT_PREFIX} {icon} {action} відкрито | {symbol}</b>\n"
        f"💰 Ціна входу: <b>{entry_price:,.2f} USDT</b>\n"
        f"📊 Розмір: {qty} {symbol.replace('USDT','')} (~{notional} USDT)\n"
        f"🤖 Впевненість: <b>{conf_pct}%</b> | {reason}\n"
        f"🎯 TP: {tp_price:,.2f} USDT (+{tp_pct*100:.1f}%)\n"
        f"🛑 SL: {sl_price:,.2f} USDT (-{sl_pct*100:.1f}%)\n"
        f"⏰ {_now_str()}"
    )
    _send(text)


# ── Закриття позиції ──────────────────────────────────────────────────────────

def on_position_closed(
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    pnl: float,
    pnl_pct: float,
    duration: str,
    reason: str,
) -> None:
    result_icon = "✅" if pnl >= 0 else "❌"
    sign = "+" if pnl >= 0 else ""

    text = (
        f"<b>{config.BOT_PREFIX} 🔴 Позиція закрита | {symbol}</b>\n"
        f"{result_icon} Результат: <b>{sign}{pnl:.2f} USDT ({sign}{pnl_pct:.2f}%)</b>\n"
        f"📈 Вхід: {entry_price:,.2f} → Вихід: {exit_price:,.2f}\n"
        f"📌 Причина: {reason}\n"
        f"⏱ Тривалість: {duration}"
    )
    _send(text)


# ── Денний ліміт ──────────────────────────────────────────────────────────────

def on_daily_limit_reached(daily_loss_usdt: float) -> None:
    text = (
        f"<b>{config.BOT_PREFIX} ⛔️ Бот зупинений</b>\n"
        f"Причина: досягнуто денний ліміт (-{config.DAILY_LOSS_LIMIT*100:.0f}%)\n"
        f"Збиток сьогодні: <b>{daily_loss_usdt:.2f} USDT</b>"
    )
    _send(text)


# ── Старт / Стоп ──────────────────────────────────────────────────────────────

def on_bot_started(mode: str) -> None:
    _send(
        f"<b>{config.BOT_PREFIX} 🚀 Бот запущено</b>\n"
        f"🤖 Модель: {config.GEMINI_MODEL}\n"
        f"🌐 Режим: <b>{mode}</b>\n"
        f"📈 Символи: {', '.join(config.SYMBOLS)}\n"
        f"⏰ {_now_str()}"
    )


def on_bot_stopped(reason: str = "вручну") -> None:
    _send(
        f"<b>{config.BOT_PREFIX} 🛑 Бот зупинено</b>\n"
        f"Причина: {reason}"
    )


def on_error(message: str) -> None:
    _send(f"<b>{config.BOT_PREFIX} ⚠️ Помилка</b>\n{message}")
