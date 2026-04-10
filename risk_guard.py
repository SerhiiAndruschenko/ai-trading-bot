"""
Захисний фільтр: валідує рішення AI-агента перед відкриттям позиції.
"""
from __future__ import annotations

import config
from ai_agent import AgentDecision
from logger import log

# Мінімальна сума ордеру на Binance Futures (USDT)
MIN_ORDER_NOTIONAL = 5.0


def validate(decision: AgentDecision, symbol: str, balance: float) -> bool:
    """
    Повертає True якщо рішення пройшло всі перевірки.
    При будь-якій невідповідності — False + лог причини.
    """
    tag = f"[{symbol}] risk_guard"

    # 1. Дія входить у допустимі значення
    if decision.action not in ("LONG", "SHORT", "WAIT"):
        log.warning(f"{tag}: невідома дія '{decision.action}'")
        return False

    # WAIT — завжди пропускаємо (не відкриваємо угоду)
    if decision.action == "WAIT":
        return False

    # 2. Мінімальна впевненість
    if decision.confidence < config.MIN_CONFIDENCE:
        log.info(
            f"{tag}: низька впевненість {decision.confidence:.2f} "
            f"(мін. {config.MIN_CONFIDENCE})"
        )
        return False

    # 3. Take-profit у межах
    if not (config.MIN_TAKE_PROFIT_PCT <= decision.take_profit_pct <= config.MAX_TAKE_PROFIT_PCT):
        log.warning(
            f"{tag}: TP {decision.take_profit_pct*100:.2f}% поза межами "
            f"[{config.MIN_TAKE_PROFIT_PCT*100:.1f}%..{config.MAX_TAKE_PROFIT_PCT*100:.1f}%]"
        )
        return False

    # 4. Stop-loss у межах
    if not (config.MIN_STOP_LOSS_PCT <= decision.stop_loss_pct <= config.MAX_STOP_LOSS_PCT):
        log.warning(
            f"{tag}: SL {decision.stop_loss_pct*100:.2f}% поза межами "
            f"[{config.MIN_STOP_LOSS_PCT*100:.1f}%..{config.MAX_STOP_LOSS_PCT*100:.1f}%]"
        )
        return False

    # 5. Risk/Reward >= 1.5
    rr = decision.take_profit_pct / decision.stop_loss_pct if decision.stop_loss_pct else 0
    if rr < 1.5:
        log.warning(f"{tag}: R/R={rr:.2f} < 1.5 (TP={decision.take_profit_pct*100:.2f}% SL={decision.stop_loss_pct*100:.2f}%)")
        return False

    # 6. Достатній баланс для мінімального ордеру
    trade_balance = min(balance, config.MAX_TRADING_BALANCE)
    position_size_usdt = trade_balance * config.RISK_PER_TRADE * config.LEVERAGE
    if position_size_usdt < MIN_ORDER_NOTIONAL:
        log.warning(
            f"{tag}: позиція {position_size_usdt:.2f} USDT < мін. {MIN_ORDER_NOTIONAL} USDT"
        )
        return False

    log.debug(
        f"{tag}: OK — {decision.action} conf={decision.confidence:.2f} "
        f"TP={decision.take_profit_pct*100:.2f}% SL={decision.stop_loss_pct*100:.2f}% R/R={rr:.2f}"
    )
    return True
