"""
AI Research Agent - Step 2: Reasoning layer
------------------------------------------
Takes the full market snapshot (every ticker's price data + every news item
from Alpaca / yfinance) and asks an LLM to:
  - read all the news and work out what's going on,
  - then, for each company, walk through it: what happened -> why ->
    what it could change -> what the stock did today -> what to expect next,
  - and give a stance + a calibrated confidence score.

Model: Google Gemini (free tier). Set GEMINI_API_KEY in .env.
Optional everywhere: if the key is missing or a call fails, analyze_market()
returns None and the app renders without analysis.
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logging.getLogger("google_genai").setLevel(logging.ERROR)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# flash-lite has a generous free-tier daily quota (the full "flash" models are
# capped at ~20 requests/day on the free tier); good enough for news synthesis.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3-flash-preview")
_ATTEMPTS_PER_MODEL = 2  # quick retries before moving to the fallback model

# JSON shape we ask the model to return. Kept in sync with the template.
_TICKER_ITEM = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "stance": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "confidence": {
            "type": "number",
            "description": "0.0-1.0 — how strongly the evidence supports the stance.",
        },
        "headline_read": {
            "type": "string",
            "description": "One punchy sentence — the takeaway for this name today.",
        },
        "what_happened": {
            "type": "string",
            "description": "The recent news for this company, synthesised into a short paragraph.",
        },
        "why_it_happened": {
            "type": "string",
            "description": "The forces behind those events — the causes, not a restatement.",
        },
        "what_could_change": {
            "type": "string",
            "description": "What this could shift for the company or the stock.",
        },
        "todays_move": {
            "type": "string",
            "description": "What the stock actually did today and how it ties (or doesn't) to the news.",
        },
        "expected_outcome": {
            "type": "string",
            "description": "What to reasonably expect in the market next, and the key things to watch.",
        },
    },
    "required": [
        "ticker", "stance", "confidence", "headline_read", "what_happened",
        "why_it_happened", "what_could_change", "todays_move", "expected_outcome",
    ],
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "market_summary": {
            "type": "string",
            "description": "2-4 sentences: what is happening across this watchlist right now.",
        },
        "top_stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "tickers": {"type": "array", "items": {"type": "string"}},
                    "impact": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["headline", "why_it_matters", "tickers", "impact"],
            },
        },
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string"},
                    "description": {"type": "string"},
                    "affected_tickers": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["theme", "description", "affected_tickers"],
            },
        },
        "tickers": {"type": "array", "items": _TICKER_ITEM},
    },
    "required": ["market_summary", "top_stories", "themes", "tickers"],
}

_SYSTEM = """You are an equity research analyst writing a briefing for the owner \
of a small technology-stock watchlist. You are handed price data and every recent \
news item (from Alpaca and Yahoo Finance) for each company.

First read ALL of the news together and work out what is actually going on — the \
real events, not the noise, and merge duplicate coverage of the same story.

Then produce:

1. A short market summary across the whole watchlist.
2. The handful of stories that matter most, each with why it matters and how big \
   the impact is.
3. The cross-cutting themes (e.g. AI capex, interest rates, regulation) and which \
   names they touch.
4. For EACH company, a clear walk-through in plain English:
   - what_happened: the recent news, pulled together into a short paragraph.
   - why_it_happened: the causes behind it — what's really driving these events.
   - what_could_change: what this could shift for the business or the stock.
   - todays_move: what the share price actually did today, and whether it lines \
     up with the news or not.
   - expected_outcome: what it's reasonable to expect in the market next, and the \
     specific things to watch for.
   - a stance (bullish / bearish / neutral) and a confidence from 0 to 1. Be \
     honest when the evidence is thin or mixed — that means LOW confidence. Only \
     go above 0.7 when the picture is clear and well supported.

Write so a smart non-expert understands it. Be specific and grounded in the \
supplied data — no hype, no filler. This is analysis, not investment advice."""


def build_context(snapshot: dict) -> str:
    """Render the snapshot into the plain-text block the model reads."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"WATCHLIST SNAPSHOT — {today}", ""]
    for ticker, d in snapshot.items():
        p = d["price"]
        lines.append(f"## {ticker}")
        if p.get("latest_close") is not None:
            chg = p.get("pct_change_1d")
            chg_s = f"{chg:+.2f}% 1d" if chg is not None else "1d change n/a"
            lines.append(f"Price: ${p['latest_close']:.2f} ({chg_s})")
        if p.get("52w_low") and p.get("52w_high"):
            lines.append(f"52-week range: ${p['52w_low']:.2f} - ${p['52w_high']:.2f}")
        if p.get("sector"):
            lines.append(f"Sector: {p['sector']}")
        news = d.get("news") or []
        if news:
            lines.append("Recent news:")
            for a in news:
                published = (a.get("published_at") or "")[:10]
                lines.append(f"  - [{published}] {a['title']} ({a['source']})")
                if a.get("description"):
                    lines.append(f"      {a['description'].strip()}")
        else:
            lines.append("Recent news: none")
        lines.append("")
    return "\n".join(lines)


def news_fingerprint(snapshot: dict) -> str:
    """A stable hash of the news set + rounded prices, so the caller can skip a
    fresh LLM call when nothing meaningful has changed since the last one."""
    h = hashlib.sha256()
    for ticker in sorted(snapshot):
        d = snapshot[ticker]
        p = d.get("price", {})
        close = p.get("latest_close")
        h.update(f"{ticker}:{round(close, 2) if close else '-'}".encode())
        for a in d.get("news") or []:
            h.update((a.get("title", "") + "|").encode("utf-8", "ignore"))
    return h.hexdigest()


_GENAI_CLIENT = None


def _client():
    """Lazily create and reuse one genai client for the process."""
    global _GENAI_CLIENT
    if _GENAI_CLIENT is None:
        from google import genai

        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set")
        _GENAI_CLIENT = genai.Client(api_key=GEMINI_API_KEY)
    return _GENAI_CLIENT


def analyze_market(snapshot: dict, model: str = None):
    """Return the combined market read as a dict, or None if unavailable."""
    if not GEMINI_API_KEY:
        return None

    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=_SYSTEM,
        response_mime_type="application/json",
        response_schema=_SCHEMA,
        thinking_config=types.ThinkingConfig(thinking_budget=1024),
        max_output_tokens=12000,
        temperature=0.4,
    )
    prompt = f"{build_context(snapshot)}\n\nProduce the briefing as JSON."

    resp = None
    used_model = None
    for candidate in ([model] if model else [GEMINI_MODEL, GEMINI_FALLBACK_MODEL]):
        for attempt in range(_ATTEMPTS_PER_MODEL):
            try:
                resp = _client().models.generate_content(
                    model=candidate, contents=prompt, config=config,
                )
                used_model = candidate
                break
            except Exception as e:  # noqa: BLE001 — analysis is best-effort
                print(f"⚠️  Market analysis via {candidate} "
                      f"(attempt {attempt + 1}) failed: {e}")
                time.sleep(1.5 * (attempt + 1))
        if resp is not None:
            break
    if resp is None:
        return None

    try:
        data = json.loads(resp.text)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"⚠️  Could not parse analysis JSON: {e}")
        return None

    by_ticker = {}
    for t in data.get("tickers", []):
        try:
            t["confidence"] = max(0.0, min(1.0, float(t.get("confidence", 0))))
        except (TypeError, ValueError):
            t["confidence"] = 0.0
        by_ticker[t.get("ticker", "").upper()] = t
    data["by_ticker"] = by_ticker
    data["generated_at"] = datetime.now(timezone.utc)
    data["model"] = used_model
    return data


def _analysis_for_chat(analysis: dict) -> str:
    """Compact text version of the briefing for the chat system prompt."""
    if not analysis:
        return "No desk briefing is available right now."
    out = ["DESK BRIEFING (what the on-screen analysis says):",
           f"Market summary: {analysis.get('market_summary', '')}"]
    for s in analysis.get("top_stories", []):
        out.append(f"- TOP STORY ({s.get('impact')}): {s.get('headline')} — "
                   f"{s.get('why_it_matters')}")
    for t in analysis.get("tickers", []):
        out.append(
            f"\n{t.get('ticker')} — stance {t.get('stance')} "
            f"(confidence {t.get('confidence')})\n"
            f"  What happened: {t.get('what_happened')}\n"
            f"  Why: {t.get('why_it_happened')}\n"
            f"  Could change: {t.get('what_could_change')}\n"
            f"  Today's move: {t.get('todays_move')}\n"
            f"  Expected next: {t.get('expected_outcome')}"
        )
    return "\n".join(out)


_CHAT_SYSTEM = """You are the analyst behind the "AI Research Agent" dashboard, \
now chatting with the person who uses it. They are looking at a page that shows, \
for a few technology stocks: the latest price and move, a news feed (from Alpaca \
and Yahoo Finance), and your written briefing on each name.

You are given that exact data and your own briefing below. Answer their questions \
from it:
- Explain in plain, easy language — like a helpful chat assistant, not a report.
- Be short. A few sentences or a tight bullet list. Expand only if asked.
- When it helps, say where something comes from ("the Alpaca news feed says…", \
"your briefing rates NVDA bullish because…").
- If the data on screen doesn't answer it, say so plainly and give your best \
general read, flagged as such.
- Never give personalised investment advice or tell them to buy or sell.

You may use light Markdown: **bold**, bullet lists with "- ", and short paragraphs."""


def chat_stream(messages: list, snapshot: dict, analysis: dict = None,
                model: str = None):
    """Yield response text chunks for a chat turn, grounded in the snapshot +
    the current briefing. `messages` is [{"role": "user"|"assistant", "content"}]."""
    from google.genai import types

    system = (
        _CHAT_SYSTEM
        + "\n\n=== LIVE DATA ON SCREEN ===\n" + build_context(snapshot)
        + "\n\n=== " + _analysis_for_chat(analysis)
    )

    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])],
        )
        for m in messages
    ]

    for candidate in ([model] if model else [GEMINI_MODEL, GEMINI_FALLBACK_MODEL]):
        try:
            stream = _client().models.generate_content_stream(
                model=candidate,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    max_output_tokens=2000,
                    temperature=0.5,
                ),
            )
            for chunk in stream:
                if chunk.text:
                    yield chunk.text
            return
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  Chat via {candidate} failed: {e}")
    raise RuntimeError("all models unavailable")


if __name__ == "__main__":
    from data_sources import build_snapshot

    snap = build_snapshot()
    result = analyze_market(snap)
    if not result:
        print("No analysis (check GEMINI_API_KEY).")
    else:
        print(json.dumps(
            {k: v for k, v in result.items() if k != "by_ticker"},
            indent=2, default=str,
        ))
