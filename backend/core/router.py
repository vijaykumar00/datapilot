"""
router.py — Intent classification and agent dispatch.

Keyword rules use whole-word/phrase matching (``\\b`` boundaries) so that e.g.
"table" no longer matches "tab", "budget" no longer matches "get" and
"withdrawal" no longer matches "draw".  "trend" alone is descriptive
(visualize); only explicitly forward-looking language routes to forecasting.
Ambiguous messages fall back to the request-scoped LLM, and any classifier
failure resolves to the safe "general" intent.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("datapilot.router")

VALID_INTENTS = {"insight", "clean", "report", "visualize", "forecast", "crossfile", "summary", "general"}

# Ordered by specificity: the first rule with a match wins.
KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("forecast", [
        "forecast", "forecasting", "predict", "prediction", "projection", "project forward",
        "extrapolate", "next month", "next quarter", "next week", "next year",
        "next \\d+ (?:days|weeks|months|quarters|years)", "future", "will be", "going to be",
    ]),
    ("visualize", [
        "chart", "plot", "graph", "visuali[sz]e", "visuali[sz]ation", "bar chart", "line chart",
        "histogram", "scatter", "pie chart", "heatmap", "draw", "trend", "trends",
    ]),
    ("clean", [
        "clean", "cleanup", "fix", "repair", "remove duplicates?", "dedupe", "deduplicate",
        "fill (?:nulls?|missing|blanks?)", "handle (?:nulls?|missing)", "data quality", "outliers?",
        "quality issues?", "missing values?", "null values?", "bad data",
        "(?:remove|drop|delete) (?:all )?(?:nulls?|missing|blanks?)", "null records", "missing records",
    ]),
    ("crossfile", [
        "join", "merge", "combine", "both files", "all files", "across files", "compare files", "multiple files",
    ]),
    ("report", [
        "report", "full analysis", "complete analysis", "detailed analysis",
    ]),
    ("summary", [
        "summari[sz]e", "summary", "overview", "executive", "key insights?", "main findings?",
        "business summary", "tell me about", "what does this data", "describe (?:this|the) (?:data|dataset|file)",
        "sheets?", "worksheets?", "tabs?",
    ]),
    ("insight", [
        "top", "bottom", "highest", "lowest", "average", "mean", "median", "count", "total", "sum",
        "how many", "how much", "which", "what is", "what are", "where", "filter", "group by", "breakdown",
        "percentage", "percent", "ratio", "show me", "list", "find", "select", "query", "compare", "by month",
        "per", "max", "min", "maximum", "minimum",
    ]),
]

_COMPILED: list[tuple[str, re.Pattern]] = [
    (intent, re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE))
    for intent, words in KEYWORD_RULES
]


def _keyword_match(message: str) -> str | None:
    for intent, pattern in _COMPILED:
        if pattern.search(message):
            return intent
    return None


CLASSIFY_SYSTEM = """You are an intent classifier for a data analysis assistant.
Classify the user message into EXACTLY ONE of these intents:
insight, clean, report, visualize, forecast, crossfile, summary, general

Return ONLY valid JSON: {"intent": "<intent>", "confidence": <0-1>}
No explanation. No markdown. Just the JSON object."""


async def classify(message: str, file_count: int = 1, llm=None) -> str:
    """Classify message intent. Returns agent name string."""
    intent = _keyword_match(message)
    if intent:
        if intent == "crossfile" and file_count < 2:
            intent = "insight"
        return intent

    if llm is None:
        return "general"
    try:
        raw = await llm.generate(f"User message: {message}\nFile count: {file_count}", system=CLASSIFY_SYSTEM, json_mode=True)
        data = json.loads(re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip())
        intent = str(data.get("intent", "general")).lower()
        confidence = float(data.get("confidence", 0) or 0)
        if intent not in VALID_INTENTS or confidence < 0.5:
            return "general"
        if intent == "crossfile" and file_count < 2:
            return "insight"
        return intent
    except Exception as exc:
        logger.warning("LLM intent classification unavailable: %s", exc)
        return "general"
