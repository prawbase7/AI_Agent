"""
AI Research Agent - Step 2: Reasoning layer
------------------------------------------
Takes the full market snapshot (every ticker's price data + every news item)
and asks an LLM for one combined read: what's happening, which stories matter
most, the cross-cutting themes, and a per-ticker stance with a confidence score.

Model: Google Gemini (free tier). Set GEMINI_API_KEY in .env.
The rest of the app treats this as optional — if the key is missing or the call
fails, `analyze_market()` returns None and the page renders without analysis.
"""

import os
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logging.getLogger("google_genai").setLevel(logging.ERROR)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
# tried if the primary model is briefly unavailable (free tier 503s under load)
GEMINI_FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-flash-latest")

# JSON shape we ask the model to return. Kept in sync with the template.
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
        "tickers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "stance": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                    "confidence": {
                        "type": "number",
                        "description": "0.0-1.0 — how strongly the evidence supports the stance.",
                    },
                    "rationale": {"type": "string"},
                    "key_factors": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "catalysts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Concrete things that could move the stock next.",
                    },
                },
                "required": [
                    "ticker", "stance", "confidence", "rationale",
                    "key_factors", "risks", "catalysts",
                ],
            },
        },
    },
    "required": ["market_summary", "top_stories", "themes", "tickers"],
}

_SYSTEM = """You are an equity research analyst producing a daily desk note for a \
small technology-stock watchlist. You are given price data and every recent news \
headline for each name. Read all of it together, not name by name.

Your job:
- Say what is actually happening across the watchlist today.
- Surface the handful of stories that matter most and explain why. Merge \
duplicate coverage of the same event.
- Name the cross-cutting themes (e.g. AI capex, interest rates, regulation) and \
which names they touch.
- For each ticker give a stance (bullish / bearish / neutral) and a calibrated \
confidence from 0 to 1. Be honest about thin evidence — low confidence is \
correct when the news is sparse or mixed. Reserve confidence above 0.7 for \
clear, well-supported situations.

Be specific and grounded in the supplied data. No hype, no filler, no \
investment advice. This is analysis, not a recommendation to trade."""


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
            lines.append(f"52-week range: ${p['52w_low']:.2f} – ${p['52w_high']:.2f}")
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

    context = build_context(snapshot)
    config = types.GenerateContentConfig(
        system_instruction=_SYSTEM,
        response_mime_type="application/json",
        response_schema=_SCHEMA,
        thinking_config=types.ThinkingConfig(thinking_budget=1024),
        max_output_tokens=8000,
        temperature=0.4,
    )
    prompt = f"{context}\n\nProduce the desk note as JSON."

    resp = None
    for candidate in ([model] if model else [GEMINI_MODEL, GEMINI_FALLBACK_MODEL]):
        try:
            resp = _client().models.generate_content(
                model=candidate, contents=prompt, config=config,
            )
            break
        except Exception as e:  # noqa: BLE001 — analysis is best-effort
            print(f"⚠️  Market analysis via {candidate} failed: {e}")
    if resp is None:
        return None
    used_model = candidate

    import json

    try:
        data = json.loads(resp.text)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"⚠️  Could not parse analysis JSON: {e}")
        return None

    # clamp confidence into [0, 1] and index tickers for easy template lookup
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


def chat_stream(messages: list, snapshot: dict, analysis: dict = None,
                model: str = None):
    """Yield response text chunks for a chat turn, grounded in the snapshot.

    `messages` is a list of {"role": "user"|"assistant", "content": str}.
    """
    from google.genai import types
    import json as _json

    context = build_context(snapshot)
    if analysis:
        slim = {k: analysis[k] for k in ("market_summary", "top_stories", "themes", "tickers") if k in analysis}
        context += "\n\nCURRENT DESK NOTE:\n" + _json.dumps(slim, indent=2, default=str)

    system = (
        _SYSTEM
        + "\n\nYou are now in a chat with the analyst who owns this watchlist. "
        "Answer their questions about the data, the news, and the desk note above. "
        "Be concise and concrete. If they ask something the data doesn't cover, say so."
        f"\n\n{context}"
    )

    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])],
        )
        for m in messages
    ]

    stream = _client().models.generate_content_stream(
        model=model or GEMINI_MODEL,
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


if __name__ == "__main__":
    from data_sources import build_snapshot

    snap = build_snapshot()
    result = analyze_market(snap)
    if not result:
        print("No analysis (check GEMINI_API_KEY).")
    else:
        import json

        print(json.dumps(
            {k: v for k, v in result.items() if k != "by_ticker"},
            indent=2, default=str,
        ))
