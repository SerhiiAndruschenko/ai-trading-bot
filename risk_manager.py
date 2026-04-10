"""
Управління станом бота: денний/місячний P&L, ліміти, збереження стану.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import config
from logger import log

STATE_FILE = Path(config.STATE_DIR) / "ai_state.json"

_DEFAULT_STATE = {
    "daily_date":    "",
    "start_balance": 0.0,
    "daily_pnl":     0.0,
    "monthly_pnl":   0.0,
    "monthly_month": "",
    "is_stopped":    False,
}


class RiskManager:
    def __init__(self) -> None:
        self._state: dict = {}
        self._load()

    # ── Персистентність ───────────────────────────────────────────────────────

    def _load(self) -> None:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, encoding="utf-8") as f:
                    self._state = json.load(f)
                log.debug(f"RiskManager: стан завантажено з {STATE_FILE}")
            except Exception as e:
                log.warning(f"RiskManager: помилка читання стану ({e}), скидаю")
                self._state = dict(_DEFAULT_STATE)
        else:
            self._state = dict(_DEFAULT_STATE)

    def _save(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"RiskManager: помилка збереження стану: {e}")

    # ── Ініціалізація дня ─────────────────────────────────────────────────────

    def init_day(self, balance: float) -> None:
        """Викликати один раз при старті або новому дні."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        month = datetime.now(timezone.utc).strftime("%Y-%m")

        if self._state.get("daily_date") != today:
            log.info(f"RiskManager: новий день {today}, скидаю денний P&L")
            self._state["daily_date"]    = today
            self._state["start_balance"] = balance
            self._state["daily_pnl"]     = 0.0

        if self._state.get("monthly_month") != month:
            log.info(f"RiskManager: новий місяць {month}, скидаю місячний P&L")
            self._state["monthly_month"] = month
            self._state["monthly_pnl"]   = 0.0

        # Відновити стан is_stopped після перезапуску
        # (вже збережено у файлі — не змінюємо)
        self._save()

    # ── P&L ──────────────────────────────────────────────────────────────────

    def record_trade_pnl(self, pnl: float) -> None:
        """Записати результат угоди в денний та місячний P&L."""
        self._state["daily_pnl"]   = round(
            self._state.get("daily_pnl", 0.0) + pnl, 4)
        self._state["monthly_pnl"] = round(
            self._state.get("monthly_pnl", 0.0) + pnl, 4)
        self._save()
        log.info(
            f"RiskManager: P&L записано {pnl:+.4f} USDT | "
            f"день={self._state['daily_pnl']:+.4f} місяць={self._state['monthly_pnl']:+.4f}"
        )

    def get_daily_pnl(self) -> float:
        return float(self._state.get("daily_pnl", 0.0))

    def get_monthly_pnl(self) -> float:
        return float(self._state.get("monthly_pnl", 0.0))

    def get_start_balance(self) -> float:
        return float(self._state.get("start_balance", 0.0))

    # ── Ліміти ────────────────────────────────────────────────────────────────

    def check_daily_limit(self, current_balance: float) -> bool:
        """
        Повертає True якщо денний ліміт збитку НЕ досягнуто.
        Якщо досягнуто — встановлює is_stopped=True і зберігає стан.
        """
        start = self._state.get("start_balance", current_balance)
        if start == 0:
            return True

        loss_pct = (start - current_balance) / start
        if loss_pct >= config.DAILY_LOSS_LIMIT:
            log.warning(
                f"RiskManager: денний ліміт досягнуто! "
                f"збиток={loss_pct*100:.2f}% "
                f"(ліміт={config.DAILY_LOSS_LIMIT*100:.0f}%)"
            )
            self._state["is_stopped"] = True
            self._save()
            return False
        return True

    # ── Стан бота ─────────────────────────────────────────────────────────────

    @property
    def is_stopped(self) -> bool:
        return bool(self._state.get("is_stopped", False))

    def stop(self) -> None:
        self._state["is_stopped"] = True
        self._save()

    def resume(self) -> None:
        """Скинути зупинку (наприклад, командою /g_resume)."""
        self._state["is_stopped"] = False
        self._save()
        log.info("RiskManager: бот відновлено")

    # ── Підрахунок угод (для статистики) ─────────────────────────────────────

    def _trades_key(self, period: str) -> str:
        return f"trades_{period}"

    def record_trade_result(self, won: bool, period: str = "daily") -> None:
        key = self._trades_key(period)
        trades = self._state.setdefault(key, {"wins": 0, "losses": 0, "total": 0})
        trades["total"] += 1
        if won:
            trades["wins"] += 1
        else:
            trades["losses"] += 1
        self._save()

    def get_trade_stats(self, period: str = "daily") -> dict:
        return self._state.get(self._trades_key(period), {"wins": 0, "losses": 0, "total": 0})

    def reset_daily_trades(self) -> None:
        self._state["trades_daily"] = {"wins": 0, "losses": 0, "total": 0}
        self._save()

    def reset_monthly_trades(self) -> None:
        self._state["trades_monthly"] = {"wins": 0, "losses": 0, "total": 0}
        self._save()


# Singleton
risk_manager = RiskManager()
