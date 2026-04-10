# AI Trading Bot — Binance USDT-M Futures

Автономний торговий бот, де **всі рішення приймає Google Gemini AI**.
Замість детермінованої стратегії (EMA/RSI) — агент аналізує ринок та самостійно вирішує коли і як торгувати.

---

## Відмінності від основного бота

| | Основний бот | AI Trading Bot |
|---|---|---|
| Рішення | EMA/RSI/MACD умови | Gemini AI |
| TP/SL | Фіксовані % | Динамічні (агент вирішує) |
| Стан | `state.json` | `ai_state.json` |
| Telegram | `/` команди | `/g_` команди |
| Статистика | Денний P&L | Денний + місячний P&L |

---

## Як отримати Gemini API ключ

1. Перейдіть на [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Натисніть **"Create API key"**
3. Виберіть або створіть Google Cloud проєкт
4. Скопіюйте ключ у `.env` → `GEMINI_API_KEY=...`

> Безкоштовний tier дозволяє ~60 запитів/хв — достатньо для сканування 3 символів кожну хвилину.

---

## Як запустити на Testnet

### 1. Клонувати та налаштувати

```bash
cd ai-trading-bot
cp .env.example .env
```

### 2. Заповнити `.env`

```env
# Binance Testnet ключі (https://testnet.binancefuture.com)
API_KEY=ваш_testnet_ключ
API_SECRET=ваш_testnet_секрет

# Gemini AI (https://aistudio.google.com/app/apikey)
GEMINI_API_KEY=ваш_gemini_ключ

# Telegram (опціонально)
TELEGRAM_BOT_TOKEN=токен_від_BotFather
TELEGRAM_CHAT_ID=ваш_chat_id
```

### 3. Встановити залежності

```bash
pip install -r requirements.txt
```

### 4. Переконатись що `TESTNET = True` у `config.py`

```python
TESTNET: bool = True
```

### 5. Запустити

```bash
python main.py
```

При старті бот:
- Перевіряє з'єднання з Binance та Gemini API
- Виводить баланс, режим, модель
- Синхронізує відкриті позиції
- Надсилає повідомлення в Telegram

---

## Як агент приймає рішення

### Що аналізує

Для кожного символу кожні `SCAN_INTERVAL` секунд (за замовчуванням 60с):

**Технічні індикатори** (15m таймфрейм, 50 свічок):
- EMA 21 / EMA 50 (тренд)
- RSI 14 (перекупленість/перепроданість)
- MACD (12, 26, 9) — імпульс
- ATR 14 — волатильність
- Обʼєм vs середній за 20 свічок

**Ринкові дані:**
- Поточна ціна
- Funding rate (сентимент ринку)
- Зміна ціни за 1г, 4г, 24г
- Останні 5 свічок OHLCV

**Стан позиції:**
- Чи є вже відкрита позиція по символу

### Що повертає

JSON з такими полями:

```json
{
  "action": "LONG",
  "confidence": 0.82,
  "take_profit_pct": 0.018,
  "stop_loss_pct": 0.009,
  "reason": "EMA21>EMA50, RSI=42 (нейтрально), обсяг x1.8"
}
```

### Фільтри перед угодою

Рішення агента додатково перевіряє `risk_guard.py`:
- `confidence >= 0.70` (MIN_CONFIDENCE)
- `take_profit_pct` у межах 0.5%–5%
- `stop_loss_pct` у межах 0.2%–3%
- Risk/Reward >= 1.5 (TP/SL)
- Достатній баланс для мінімального ордеру

---

## Telegram команди `/g_`

| Команда | Опис |
|---------|------|
| `/g_status` | Відкриті позиції, стан бота (активний/пауза/зупинено) |
| `/g_today` | P&L за сьогодні, кількість угод, winrate |
| `/g_month` | P&L за поточний місяць, статистика |
| `/g_pause` | Пауза — нові угоди не відкриваються, поточні залишаються |
| `/g_resume` | Відновити торгівлю після паузи або денного ліміту |
| `/g_stop` | Закрити всі позиції і зупинити бота |
| `/g_info` | Повна інформація: баланс, P&L, позиції, налаштування |

### Приклад `/g_info`

```
[AI] 🎒 Стан рахунку 📝
TESTNET 🧪

💰 Баланс
Доступно: 487.32 USDT
Гаманець: 500.00 USDT
Нереаліз. PnL: +2.41 USDT

📊 Реалізований PnL
Сьогодні: +5.23 USDT
Місяць: +12.47 USDT

📂 Відкриті позиції: 1
  └ 🟢 LONG BTCUSDT | Вхід: 84,250.00
    P&L: +2.41 USDT (+1.15%) | 1г 23хв

🤖 Модель: gemini-2.5-pro-preview-03-25
🎯 Впевненість мін.: 70%
📈 Символи: BTCUSDT, ETHUSDT, SOLUSDT
⚙️ Плече: x5 | Ризик: 2%
📅 Дані станом на 10.04.2026 14:32 UTC
```

---

## Структура проєкту

```
ai-trading-bot/
├── main.py           # Головний цикл, startup checks, graceful shutdown
├── config.py         # Всі параметри (env + константи)
├── binance_client.py # REST API клієнт (ціни, ордери, баланс)
├── data_collector.py # Збір ринкових даних + індикатори
├── ai_agent.py       # Gemini AI агент (аналіз → рішення)
├── risk_guard.py     # Валідація рішень агента
├── trader.py         # Відкриття/закриття позицій, SL/TP моніторинг
├── risk_manager.py   # Денний/місячний P&L, ліміти, ai_state.json
├── notifications.py  # Telegram повідомлення
├── telegram_bot.py   # /g_ команди
├── logger.py         # Логування (консоль + bot.log)
├── .env              # Ваші ключі (не комітити!)
├── .env.example      # Шаблон
├── ai_state.json     # Стан бота (auto-generated)
└── requirements.txt
```

---

## Параметри в `config.py`

| Параметр | Значення | Опис |
|----------|----------|------|
| `TESTNET` | `True` | Testnet/Mainnet |
| `LEVERAGE` | `5` | Плече |
| `RISK_PER_TRADE` | `0.02` | 2% від балансу на угоду |
| `DAILY_LOSS_LIMIT` | `0.05` | Стоп при -5% за день |
| `MAX_TRADING_BALANCE` | `500` | Максимум USDT для торгівлі |
| `MAX_OPEN_TRADES_GLOBAL` | `2` | Макс. одночасних позицій |
| `MIN_CONFIDENCE` | `0.70` | Мін. впевненість агента |
| `SCAN_INTERVAL` | `60` | Секунд між скануваннями |

---

## Безпека

- Ніколи не комітьте `.env` у git
- Додайте `.env` та `ai_state.json` до `.gitignore`
- На Mainnet рекомендується починати з малих сум
- Тестуйте завжди на Testnet першочергово
