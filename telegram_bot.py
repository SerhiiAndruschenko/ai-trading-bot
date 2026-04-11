"""
Telegram-бот для управління AI-трейдером.
Всі команди мають префікс g_.
Відповідає тільки TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import binance_client as bc
import trader
import notifications
from risk_manager import risk_manager
from logger import log

# ── Стан паузи ───────────────────────────────────────────────────────────────
_paused: bool = False


def is_paused() -> bool:
    return _paused


# ── Авторизація ───────────────────────────────────────────────────────────────

def _auth(update: Update) -> bool:
    """
    Authorize by user ID or chat ID.
    Works in private chats, groups, and topics.
    TELEGRAM_CHAT_ID = your personal user ID (from @userinfobot).
    """
    if not config.TELEGRAM_CHAT_ID:
        return True  # no filter -- dev mode

    user = update.effective_user
    chat = update.effective_chat
    uid  = str(user.id) if user else ""
    cid  = str(chat.id) if chat else ""

    # Accept if sender user ID OR chat ID matches config
    if uid == config.TELEGRAM_CHAT_ID or cid == config.TELEGRAM_CHAT_ID:
        return True

    log.warning("TG: unauthorized | user_id=%s chat_id=%s | expected %s",
                uid, cid, config.TELEGRAM_CHAT_ID)
    return False


async def _reply(update: Update, text: str) -> None:
    """Send reply in the same chat/thread where command was received."""
    try:
        await update.message.reply_text(text=text, parse_mode="HTML")
    except Exception as e:
        log.error("TG _reply error: %s", e)
        # Fallback: plain text
        try:
            await update.message.reply_text(text=text)
        except Exception as e2:
            log.error("TG _reply fallback error: %s", e2)


# ── /g_status ─────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.debug("TG: /g_status from user=%s chat=%s",
              update.effective_user.id if update.effective_user else "?",
              update.effective_chat.id if update.effective_chat else "?")
    if not _auth(update):
        return

    open_trades = trader.get_open_trades()
    mode        = "TESTNET" if config.TESTNET else "MAINNET"
    state       = "⏸ Пауза" if _paused else ("⛔️ Зупинено" if risk_manager.is_stopped else "✅ Активний")

    lines = [
        f"<b>{config.BOT_PREFIX} 📊 Статус</b>",
        f"🌐 Режим: {mode}",
        f"🔘 Стан: {state}",
        f"📂 Відкритих позицій: {len(open_trades)}",
    ]

    for sym, t in open_trades.items():
        price    = bc.get_symbol_price(sym)
        entry    = t["entry_price"]
        side     = t["side"]
        pnl_raw  = (price - entry) if side == "LONG" else (entry - price)
        pnl_pct  = pnl_raw / entry * 100 if entry else 0
        pnl_usdt = pnl_raw * t["qty"]
        sign     = "+" if pnl_usdt >= 0 else ""
        icon     = "🟢" if side == "LONG" else "🔴"
        lines.append(
            f"\n  {icon} {side} {sym}\n"
            f"  Вхід: {entry:,.2f} | Ціна: {price:,.2f}\n"
            f"  P&L: {sign}{pnl_usdt:.2f} USDT ({sign}{pnl_pct:.2f}%)"
        )

    await _reply(update, "\n".join(lines))


# ── /g_today ──────────────────────────────────────────────────────────────────

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update):
        return

    pnl    = risk_manager.get_daily_pnl()
    stats  = risk_manager.get_trade_stats("daily")
    total  = stats["total"]
    wins   = stats["wins"]
    wr     = f"{wins/total*100:.0f}%" if total else "—"
    sign   = "+" if pnl >= 0 else ""

    text = (
        f"<b>{config.BOT_PREFIX} 📅 Сьогодні</b>\n"
        f"💰 P&L: <b>{sign}{pnl:.2f} USDT</b>\n"
        f"📊 Угод: {total} | Профітних: {wins} | Winrate: {wr}"
    )
    await _reply(update, text)


# ── /g_month ──────────────────────────────────────────────────────────────────

async def cmd_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update):
        return

    pnl   = risk_manager.get_monthly_pnl()
    stats = risk_manager.get_trade_stats("monthly")
    total = stats["total"]
    wins  = stats["wins"]
    wr    = f"{wins/total*100:.0f}%" if total else "—"
    sign  = "+" if pnl >= 0 else ""
    month = datetime.now(timezone.utc).strftime("%B %Y")

    text = (
        f"<b>{config.BOT_PREFIX} 📆 Місяць ({month})</b>\n"
        f"💰 P&L: <b>{sign}{pnl:.2f} USDT</b>\n"
        f"📊 Угод: {total} | Профітних: {wins} | Winrate: {wr}"
    )
    await _reply(update, text)


# ── /g_pause ──────────────────────────────────────────────────────────────────

async def cmd_pause(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update):
        return

    global _paused
    _paused = True
    log.info("TG: бот на паузі (нові угоди не відкриваються)")
    await _reply(update, f"<b>{config.BOT_PREFIX} ⏸ Бот поставлено на паузу</b>\nНові угоди не відкриваються.")


# ── /g_resume ─────────────────────────────────────────────────────────────────

async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update):
        return

    global _paused
    _paused = False
    risk_manager.resume()
    log.info("TG: бот відновлено")
    await _reply(update, f"<b>{config.BOT_PREFIX} ▶️ Бот відновлено</b>\nТоргівля активна.")


# ── /g_stop ───────────────────────────────────────────────────────────────────

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update):
        return

    await _reply(update, f"<b>{config.BOT_PREFIX} ⛔️ Закриваю всі позиції...</b>")
    trader.close_all_positions("Команда /g_stop")
    risk_manager.stop()
    log.info("TG: /g_stop — всі позиції закрито, бот зупинено")
    await _reply(update, f"<b>{config.BOT_PREFIX} 🛑 Бот зупинено</b>\nВсі позиції закрито.")


# ── /g_info ───────────────────────────────────────────────────────────────────

async def cmd_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update):
        return

    mode = "TESTNET 🧪" if config.TESTNET else "MAINNET 🌐"
    available, wallet = bc.get_futures_balance()

    # Unrealized PnL із відкритих позицій
    open_positions = bc.get_open_positions()
    unrealized_pnl = sum(float(p.get("unrealizedProfit", 0)) for p in open_positions)

    daily_pnl   = risk_manager.get_daily_pnl()
    monthly_pnl = risk_manager.get_monthly_pnl()

    open_trades = trader.get_open_trades()
    now_str     = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")

    def sign_str(v: float) -> str:
        return f"+{v:.2f}" if v >= 0 else f"{v:.2f}"

    lines = [
        f"<b>{config.BOT_PREFIX} 🎒 Стан рахунку 📝</b>",
        f"<i>{mode}</i>",
        "",
        "💰 <b>Баланс</b>",
        f"Доступно: <b>{available:.2f} USDT</b>",
        f"Гаманець: {wallet:.2f} USDT",
        f"Нереаліз. PnL: {sign_str(unrealized_pnl)} USDT",
        "",
        "📊 <b>Реалізований PnL</b>",
        f"Сьогодні: <b>{sign_str(daily_pnl)} USDT</b>",
        f"Місяць: {sign_str(monthly_pnl)} USDT",
        "",
        f"📂 <b>Відкриті позиції: {len(open_trades)}</b>",
    ]

    for sym, t in open_trades.items():
        price   = bc.get_symbol_price(sym)
        entry   = t["entry_price"]
        side    = t["side"]
        qty     = t["qty"]
        pnl_raw = (price - entry) if side == "LONG" else (entry - price)
        pnl_pct = pnl_raw / entry * 100 if entry else 0
        pnl_u   = pnl_raw * qty
        dur     = _duration_str(t["opened_at"])
        icon    = "🟢" if side == "LONG" else "🔴"
        lines.append(
            f"  └ {icon} {side} {sym} | Вхід: {entry:,.2f}\n"
            f"    P&L: {sign_str(pnl_u)} USDT ({sign_str(pnl_pct)}%) | {dur}"
        )

    lines += [
        "",
        f"🤖 Модель: {config.GEMINI_MODEL}",
        f"🎯 Впевненість мін.: {config.MIN_CONFIDENCE*100:.0f}%",
        f"📈 Символи: {', '.join(config.SYMBOLS)}",
        f"⚙️ Плече: x{config.LEVERAGE} | Ризик: {config.RISK_PER_TRADE*100:.0f}%",
        f"📅 Дані станом на {now_str} UTC",
    ]

    await _reply(update, "\n".join(lines))


def _duration_str(opened_at) -> str:
    from datetime import datetime, timezone
    delta = datetime.now(timezone.utc) - opened_at
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m = rem // 60
    return f"{h}г {m}хв" if h else f"{m}хв"


# ── Запуск бота ───────────────────────────────────────────────────────────────

def start_bot() -> Optional[threading.Thread]:
    """
    Запускає Telegram-бот у окремому потоці.
    Повертає Thread або None якщо Telegram не налаштовано.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.info("Telegram не налаштовано — пропускаємо запуск бота")
        return None

    def _run():
        app = (
            Application.builder()
            .token(config.TELEGRAM_BOT_TOKEN)
            .build()
        )

        # Реєстрація команд
        app.add_handler(CommandHandler("g_status", cmd_status))
        app.add_handler(CommandHandler("g_today",  cmd_today))
        app.add_handler(CommandHandler("g_month",  cmd_month))
        app.add_handler(CommandHandler("g_pause",  cmd_pause))
        app.add_handler(CommandHandler("g_resume", cmd_resume))
        app.add_handler(CommandHandler("g_stop",   cmd_stop))
        app.add_handler(CommandHandler("g_info",   cmd_info))

        # Передаємо app у notifications для надсилання через один event loop
        notifications.set_app(app)

        # Error handler
        async def _tg_error(upd, ctx):
            log.error("TG error: %s | update=%s",
                      ctx.error, str(upd)[:200] if upd else "None")
        app.add_error_handler(_tg_error)

        # Debug: log ALL incoming messages to confirm bot receives them
        async def _debug_all(upd, ctx):
            msg = upd.message or upd.edited_message
            if msg:
                log.info("TG received: chat_id=%s user_id=%s text=%s",
                         msg.chat_id, msg.from_user.id if msg.from_user else '?',
                         repr((msg.text or '')[:60]))
        app.add_handler(MessageHandler(filters.ALL, _debug_all), group=99)

        log.info("Telegram bot started (polling)")
        app.run_polling(
            drop_pending_updates=False,
            allowed_updates=Update.ALL_TYPES,
        )

    t = threading.Thread(target=_run, name="TelegramBot", daemon=True)
    t.start()
    return t
