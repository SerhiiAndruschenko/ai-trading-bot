"""
AI agent based on Google Gemini (google-genai SDK).
Receives market data and returns AgentDecision.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from google import genai
from google.genai import types

import config
from logger import log

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


@dataclass
class AgentDecision:
    action: str
    confidence: float
    take_profit_pct: float
    stop_loss_pct: float
    reason: str


_DEFAULT_WAIT = AgentDecision(
    action="WAIT",
    confidence=0.0,
    take_profit_pct=0.015,
    stop_loss_pct=0.008,
    reason="parse error",
)

_SYSTEM_PROMPT = (
    "You are an AI trading agent on Binance USDT-M Futures.\n"
    "Analyze market data and make trading decisions.\n\n"
    "Rules:\n"
    "- If confidence < 0.70 -> always WAIT\n"
    "- If open position exists for symbol -> WAIT\n"
    "- TP 0.005..0.05, SL 0.002..0.03\n"
    "- Risk/Reward >= 1.5 (take_profit_pct / stop_loss_pct)\n"
    "- Reply ONLY with valid JSON, no markdown"
)

_PROMPT_TPL = (
    "Symbol: {symbol}\n"
    "Balance: {balance} USDT\n"
    "Current price: {price}\n"
    "Open position: {open_position}\n\n"
    "Indicators:\n"
    "EMA21={ema21:.4f} | EMA50={ema50:.4f} | Trend: {trend}\n"
    "RSI={rsi:.1f}\n"
    "MACD={macd:.4f} | Signal={macd_signal:.4f} | Hist={macd_hist:.4f}\n"
    "ATR={atr:.4f}\n"
    "Volume: current={volume:.0f} | avg={avg_volume:.0f} | ratio={vol_ratio:.2f}x\n\n"
    "Price dynamics:\n"
    "15m: {change_15m:+.2f}% | 1h: {change_1h:+.2f}% | 4h: {change_4h:+.2f}% | 24h: {change_24h:+.2f}%\n"
    "Funding rate: {funding_rate:.4f}%\n\n"
    "Rule: if the price has already moved more than 1% in the last hour in the direction\n"
    "of the potential trade (e.g. +1% for LONG or -1% for SHORT), confidence MUST be\n"
    "below 0.60 — reply WAIT. Do not enter after a strong impulse; wait for a\n"
    "correction or consolidation.\n\n"
    "Last 5 candles:\n"
    "{last_5_candles}\n\n"
    "Return JSON only (no markdown):\n"
    "{{\n"
    "  \"action\": \"LONG\" or \"SHORT\" or \"WAIT\",\n"
    "  \"confidence\": 0.0-1.0,\n"
    "  \"take_profit_pct\": 0.005-0.05,\n"
    "  \"stop_loss_pct\": 0.002-0.03,\n"
    "  \"reason\": \"explanation max 100 chars\"\n"
    "}}"
)


def _strip_markdown(text: str) -> str:
    """Remove ```json ... ``` fences robustly."""
    text = text.strip()

    # Remove opening fence: ```json or ```
    if text.startswith("```"):
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1:]
        else:
            # single-line: strip backticks and language tag
            text = text.lstrip("`").strip()
            if text.startswith("json"):
                text = text[4:].strip()

    # Remove closing fence
    if text.endswith("```"):
        text = text[:-3]

    return text.strip()




def _safe_text(resp):
    """Extract text from Gemini response; handles MAX_TOKENS and STOP."""
    try:
        cands = resp.candidates
        if cands:
            candidate = cands[0]
            if candidate.content and candidate.content.parts:
                parts_text = "".join(
                    p.text for p in candidate.content.parts
                    if hasattr(p, "text") and p.text
                )
                if parts_text:
                    return parts_text
            reason = getattr(cands[0], "finish_reason", "unknown")
            log.warning("Gemini: no text in parts, finish_reason=%s", reason)
    except Exception:
        pass
    try:
        text = resp.text
        if text:
            return text
    except Exception:
        pass
    return None

def _parse_response(raw):
    try:
        cleaned = _strip_markdown(raw)
        data = json.loads(cleaned)
        return AgentDecision(
            action=str(data.get("action", "WAIT")).upper(),
            confidence=float(data.get("confidence", 0.0)),
            take_profit_pct=float(data.get("take_profit_pct", 0.015)),
            stop_loss_pct=float(data.get("stop_loss_pct", 0.008)),
            reason=str(data.get("reason", ""))[:100],
        )
    except Exception as e:
        log.error("AI agent parse error: %s | raw=%s", e, raw[:200])
        return _DEFAULT_WAIT


def analyze(symbol, market_data, balance):
    if not market_data:
        log.warning("[%s] No market data for AI agent", symbol)
        return _DEFAULT_WAIT

    d = market_data
    trend = "UP" if d.get("ema21", 0) > d.get("ema50", 0) else "DOWN"

    pos = d.get("open_position")
    if pos:
        side = "LONG" if float(pos.get("positionAmt", 0)) > 0 else "SHORT"
        open_pos_str = side + " qty=" + str(pos.get("positionAmt"))
    else:
        open_pos_str = "None"

    user_prompt = _PROMPT_TPL.format(
        symbol=symbol,
        balance=round(balance, 2),
        price=d.get("price", 0),
        open_position=open_pos_str,
        ema21=d.get("ema21", 0),
        ema50=d.get("ema50", 0),
        trend=trend,
        rsi=d.get("rsi", 0),
        macd=d.get("macd", 0),
        macd_signal=d.get("macd_signal", 0),
        macd_hist=d.get("macd_hist", 0),
        atr=d.get("atr", 0),
        volume=d.get("volume", 0),
        avg_volume=d.get("avg_volume", 0),
        vol_ratio=d.get("vol_ratio", 1.0),
        change_15m=d.get("change_15m", 0),
        change_1h=d.get("change_1h", 0),
        change_4h=d.get("change_4h", 0),
        change_24h=d.get("change_24h", 0),
        funding_rate=d.get("funding_rate", 0),
        last_5_candles=d.get("last_5_candles", ""),
    )

    try:
        response = _get_client().models.generate_content(
            model=config.GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                temperature=0.2,
                max_output_tokens=2048,
            ),
        )
        raw_text = _safe_text(response)
        if raw_text is None:
            log.warning("[%s] Gemini returned empty/blocked response -- WAIT", symbol)
            return _DEFAULT_WAIT
        log.debug("[%s] Gemini response: %s", symbol, raw_text)
    except Exception as e:
        log.error("[%s] Gemini API error: %s", symbol, e)
        return _DEFAULT_WAIT

    decision = _parse_response(raw_text)
    log.info(
        "[%s] Decision: %s | conf=%.2f | TP=%.2f%% SL=%.2f%% | %s",
        symbol, decision.action, decision.confidence,
        decision.take_profit_pct * 100, decision.stop_loss_pct * 100,
        decision.reason,
    )
    return decision


def _list_available_models():
    """Log available Gemini models to help debug 404 errors."""
    try:
        names = [m.name for m in _get_client().models.list()
                 if "gemini" in m.name.lower()]
        log.info("Available Gemini models: %s", ", ".join(names[:20]))
    except Exception as e:
        log.debug("Could not list models: %s", e)


def check_gemini_connection():
    try:
        resp = _get_client().models.generate_content(
            model=config.GEMINI_MODEL,
            contents="Reply with one word: OK",
            config=types.GenerateContentConfig(max_output_tokens=64),
        )
        text = _safe_text(resp)
        if text is not None:
            log.info("Gemini API: connection OK | model=%s | reply=%s",
                     config.GEMINI_MODEL, text.strip()[:30])
            return True
        log.error(
            "Gemini API: empty/truncated response (model=%s). Check GEMINI_MODEL in .env.",
            config.GEMINI_MODEL,
        )
        _list_available_models()
        return False
    except Exception as e:
        log.error("Gemini API: FAILED - %s", e)
        _list_available_models()
        return False
