import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Режим роботи ──────────────────────────────────────────────────────────────
TESTNET: bool = True

# ── Binance API ───────────────────────────────────────────────────────────────
API_KEY: str    = os.getenv("API_KEY", "")
API_SECRET: str = os.getenv("API_SECRET", "")

# ── Gemini AI ─────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str   = "gemini-2.5-pro-preview-03-25"

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str   = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_THREAD_ID: str = os.getenv("TELEGRAM_THREAD_ID", "")
BOT_PREFIX: str         = "[AI]"

# ── Торгові символи ───────────────────────────────────────────────────────────
SYMBOLS: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEFRAME: str     = "15m"
CANDLES_LIMIT: int = 50

# ── Ризик-менеджмент ──────────────────────────────────────────────────────────
LEVERAGE: int              = 5
RISK_PER_TRADE: float      = 0.02        # 2% від балансу
DAILY_LOSS_LIMIT: float    = 0.05        # 5%
MAX_TRADING_BALANCE: float = float(os.getenv("MAX_TRADING_BALANCE", "500"))
MAX_OPEN_TRADES_GLOBAL: int = 2

# ── AI рішення ────────────────────────────────────────────────────────────────
MIN_CONFIDENCE: float      = 0.70
MAX_TAKE_PROFIT_PCT: float = 0.05        # 5%
MAX_STOP_LOSS_PCT: float   = 0.03        # 3%
MIN_TAKE_PROFIT_PCT: float = 0.005       # 0.5%
MIN_STOP_LOSS_PCT: float   = 0.002       # 0.2%

# ── Основний цикл ─────────────────────────────────────────────────────────────
SCAN_INTERVAL: int = 60   # секунд між ітераціями

# ── Шлях до стану ─────────────────────────────────────────────────────────────
STATE_DIR: str = os.getenv("STATE_DIR", str(Path(__file__).parent))
