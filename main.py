"""
AI Trading Bot — головний модуль.
Торгові рішення приймає Gemini AI через api.
"""
from __future__ import annotations

import signal
import sys
import time

import config
import binance_client as bc
import data_collector
import ai_agent
import risk_guard
import trader
import notifications
import telegram_bot
from risk_manager import risk_manager
from logger import log

# ── Стан паузи/зупинки (доступний з telegram_bot) ───────────────────────────
bot_state = {
    "paused":  False,   # лише нові угоди
    "running": True,    # головний цикл
}

_iteration = 0


# ── Ініціалізація ─────────────────────────────────────────────────────────────

def startup_checks() -> None:
    """Перевірки при старті."""
    log.info("=" * 60)
    log.info(f"  AI Trading Bot | {config.GEMINI_MODEL}")
    log.info(f"  Режим: {'TESTNET' if config.TESTNET else 'MAINNET'}")
    log.info(f"  Символи: {', '.join(config.SYMBOLS)}")
    log.info("=" * 60)

    # 1. Binance API
    log.info("Перевірка з'єднання з Binance...")
    if not bc.check_connection():
        log.error("Не вдалося підключитися до Binance API. Завершення.")
        sys.exit(1)
    log.info("✅ Binance API: OK")

    # 2. Gemini API
    log.info("Перевірка з'єднання з Gemini...")
    if not ai_agent.check_gemini_connection():
        log.error("Не вдалося підключитися до Gemini API. Завершення.")
        sys.exit(1)
    log.info("✅ Gemini API: OK")

    # 3. Баланс
    available, wallet = bc.get_futures_balance()
    log.info(f"💰 Баланс: доступно={available:.2f} USDT | гаманець={wallet:.2f} USDT")
    log.info(f"📊 Ліміт торгівлі: {config.MAX_TRADING_BALANCE} USDT")
    log.info(f"⚙️ Плече: x{config.LEVERAGE} | Ризик: {config.RISK_PER_TRADE*100:.0f}% | "
             f"Мін. впевненість: {config.MIN_CONFIDENCE*100:.0f}%")

    # 4. Ініціалізація RiskManager
    risk_manager.init_day(available)

    # 5. Синхронізація позицій
    log.info("Синхронізація відкритих позицій...")
    trader.reconcile_open_trades()

    # 6. Telegram
    telegram_bot.start_bot()

    # 7. Повідомлення про старт
    mode = "TESTNET" if config.TESTNET else "MAINNET"
    notifications.on_bot_started(mode)

    log.info("=" * 60)
    log.info("Бот запущено. Починаємо головний цикл...")


# ── Graceful shutdown ─────────────────────────────────────────────────────────

def _shutdown(signum=None, frame=None) -> None:
    log.info("Отримано сигнал зупинки...")
    bot_state["running"] = False
    trader.close_all_positions("завершення роботи")
    notifications.on_bot_stopped("вручну")
    log.info("Бот зупинено.")
    sys.exit(0)


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)


# ── Головний цикл ─────────────────────────────────────────────────────────────

def main_loop() -> None:
    global _iteration
    log.info(f"Інтервал сканування: {config.SCAN_INTERVAL}с")

    while bot_state["running"]:
        _iteration += 1
        try:
            _one_iteration()
        except Exception as e:
            log.error(f"Помилка в головному циклі: {e}", exc_info=True)

        time.sleep(config.SCAN_INTERVAL)


def _one_iteration() -> None:
    global _iteration

    # ── 1. Перевірка стану ────────────────────────────────────────────────────
    if telegram_bot.is_paused():
        log.debug("Бот на паузі — пропускаємо ітерацію")
        return

    if risk_manager.is_stopped:
        log.debug("Бот зупинено (ліміт або /g_stop)")
        return

    # ── 2. Денний ліміт ───────────────────────────────────────────────────────
    available, _ = bc.get_futures_balance()
    if not risk_manager.check_daily_limit(available):
        daily_pnl = risk_manager.get_daily_pnl()
        notifications.on_daily_limit_reached(abs(daily_pnl))
        trader.close_all_positions("денний ліміт")
        return

    # ── 3. Перевірка SL/TP для відкритих позицій ─────────────────────────────
    trader.check_sl_tp_all()

    # ── 4. Глобальний ліміт угод ─────────────────────────────────────────────
    open_count = trader.count_open_trades()
    if open_count >= config.MAX_OPEN_TRADES_GLOBAL:
        if _iteration % 5 == 0:
            log.info(
                f"MAX_OPEN_TRADES_GLOBAL досягнуто ({open_count}/"
                f"{config.MAX_OPEN_TRADES_GLOBAL}) — не відкриваємо нові"
            )
        return

    # ── 5. Сканування символів ────────────────────────────────────────────────
    for symbol in config.SYMBOLS:
        if not bot_state["running"]:
            break
        if open_count >= config.MAX_OPEN_TRADES_GLOBAL:
            break

        try:
            _process_symbol(symbol, available)
        except Exception as e:
            log.error(f"[{symbol}] Помилка обробки: {e}", exc_info=True)

    # ── 6. Verbose лог кожні 5 ітерацій ──────────────────────────────────────
    if _iteration % 5 == 0:
        open_t = trader.get_open_trades()
        log.info(
            f"[Ітерація {_iteration}] "
            f"Відкритих угод: {len(open_t)} | "
            f"Баланс: {available:.2f} USDT | "
            f"Денний P&L: {risk_manager.get_daily_pnl():+.4f} USDT"
        )


def _process_symbol(symbol: str, balance: float) -> None:
    # a. Збір даних
    data = data_collector.collect_market_data(symbol)
    if not data:
        log.warning(f"[{symbol}] Пропускаємо — немає даних")
        return

    # b. Рішення агента
    decision = ai_agent.analyze(symbol, data, balance)

    # c. Логування рішення
    log.info(
        f"[{symbol}] Рішення агента: {decision.action} | "
        f"confidence={decision.confidence:.2f} | "
        f"{decision.reason}"
    )

    # d. Валідація
    if not risk_guard.validate(decision, symbol, balance):
        return

    # e. Відкриваємо позицію
    trader.open_position(
        symbol=symbol,
        action=decision.action,
        tp_pct=decision.take_profit_pct,
        sl_pct=decision.stop_loss_pct,
        balance=balance,
        confidence=decision.confidence,
        reason=decision.reason,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    startup_checks()
    try:
        main_loop()
    except KeyboardInterrupt:
        _shutdown()
