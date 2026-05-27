"""
router.py — Intent classification and agent dispatch.
Strategy: keyword matching first (0ms), LLM fallback for ambiguous queries.
"""

import json
import logging
import re

from core.llm_client import get_llm_client

logger = logging.getLogger("datapilot.router")

# --- Keyword rules (ordered by specificity) ---
KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("visualize", [
        "chart", "plot", "graph", "visuali", "bar chart", "line chart",
        "histogram", "scatter", "pie chart", "heatmap", "show me a",
        "draw", "display a", "create a chart", "create a graph",
    ]),
    ("forecast", [
        "forecast", "predict", "trend", "future", "next month", "next quarter",
        "next week", "projection", "extrapolate", "will be", "going to be",
    ]),
    ("clean", [
        "clean", "fix", "repair", "remove duplicate", "fill null", "fill missing",
        "handle null", "handle missing", "data quality", "outlier", "quality issue",
        "check for issue", "check the data", "check this data", "data problem",
        "missing value", "null value", "bad data",
    ]),
    ("crossfile", [
        "join", "merge", "combine", "both files", "all files", "across files",
        "compare files", "multiple files",
    ]),
    ("summary", [
        "summarize", "summary", "overview", "executive", "explain why",
        "key insight", "main finding", "business summary", "tell me about",
        "what does this data", "describe this", "sheet", "sheets",
        "worksheet", "worksheets", "tab", "tabs",
    ]),
    ("report", [
        "report", "full analysis", "complete analysis", "generate report",
        "analysis report", "detailed analysis",
    ]),
    ("insight", [
        "top", "bottom", "highest", "lowest", "average", "mean", "count",
        "total", "sum", "how many", "which", "what is", "where", "filter",
        "group by", "breakdown", "percentage", "ratio", "show me the",
        "list", "find", "get", "select", "query",
    ]),
]


def _keyword_match(message: str) -> str | None:
    """Fast O(n) keyword scan. Returns intent or None."""
    lower = message.lower()
    for intent, keywords in KEYWORD_RULES:
        for kw in keywords:
            if kw in lower:
                logger.debug(f"Keyword '{kw}' → intent='{intent}'")
                return intent
    return None


CLASSIFY_SYSTEM = """You are an intent classifier for a data analysis assistant.
Classify the user message into EXACTLY ONE of these intents:
insight, clean, report, visualize, forecast, crossfile, summary, general

Return ONLY valid JSON: {"intent": "<intent>", "confidence": <0-1>}
No explanation. No markdown. Just the JSON object."""


async def classify(message: str, file_count: int = 1) -> str:
    """Classify message intent. Returns agent name string."""
    # Fast path
    intent = _keyword_match(message)
    if intent:
        # Adjust crossfile intent if only one file loaded
        if intent == "crossfile" and file_count < 2:
            intent = "insight"
        return intent

    # Slow path — ask LLM
    logger.info("No keyword match — using LLM classification")
    llm = get_llm_client()
    prompt = f"User message: {message}\nFile count: {file_count}"
    raw = await llm.generate(prompt, system=CLASSIFY_SYSTEM, json_mode=True)

    try:
        data = json.loads(raw)
        intent = data.get("intent", "general")
        confidence = data.get("confidence", 0)
        logger.info(f"LLM classified '{intent}' (confidence={confidence:.2f})")
        valid = {"insight", "clean", "report", "visualize", "forecast", "crossfile", "summary", "general"}
        return intent if intent in valid else "general"
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"LLM classification parse error: {e} | raw='{raw}'")
        return "general"
