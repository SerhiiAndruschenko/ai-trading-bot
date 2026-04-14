import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TESTNET: bool = True

API_KEY: str    = os.getenv("API_KEY", "")
API_SECRET: str = os.getenv("API_SECRET", "")

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str   = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str   = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_THREAD_ID: str = os.getenv("TELEGRAM_THREAD_ID", "")
BOT_PREFIX: str         = "[AI]"

SYMBOLS: list = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEFRAME: str     = "15m"
CANDLES_LIMIT: int = 50

LEVERAGE: int              = 5
RISK_PER_TRADE: float      = 0.02
DAILY_LOSS_LIMIT: float    = 0.05
MAX_TRADING_BALANCE: float = float(os.getenv("MAX_TRADING_BALANCE", "500"))
MAX_OPEN_TRADES_GLOBAL: int = 2

MIN_CONFIDENCE: float      = 0.70
MAX_TAKE_PROFIT_PCT: float = 0.05
MAX_STOP_LOSS_PCT: float   = 0.03
MIN_TAKE_PROFIT_PCT: float = 0.005
MIN_STOP_LOSS_PCT: float   = 0.002

SCAN_INTERVAL: int = 60

# Пауза після закриття угоди по символу (секунди).
# Запобігає повторному входу одразу після TP/SL.
SYMBOL_COOLDOWN_SEC: int = 900  # 15 хвилин

STATE_DIR: str = os.getenv("STATE_DIR", str(Path(__file__).parent))
