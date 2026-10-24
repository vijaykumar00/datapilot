"""
question_engine.py — answers common spreadsheet questions without calling an AI model.

Most business questions follow a handful of shapes: a total / average / count,
optionally "by" a category or a time period, optionally the top or bottom N,
optionally filtered to a value ("in West", "in 2026").  This module recognises
those shapes and builds the DuckDB SQL directly from the dataset's columns.

Design rules
------------
* **Never guess.**  Every meaningful word in the question must be understood
  (a grammar word, a column, or a value that exists in the data).  Any unknown
  word, ambiguous column or unsupported phrasing returns ``None`` and the caller
  falls back to the AI model.  A wrong confident answer is worse than an AI call.
* Identifiers are double-quoted and literals single-quoted with escaping; the SQL
  still runs through the same sandbox/validator as AI-written SQL.
* Pure function of (question, DataFrame): no I/O, no global state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

# ── Vocabulary ───────────────────────────────────────────────────────────────

AGG_WORDS = {
    "total": "sum", "sum": "sum", "overall": "sum",
    "average": "avg", "avg": "avg", "mean": "avg",
    "median": "median",
    "maximum": "max", "max": "max",
    "minimum": "min", "min": "min",
}
# Superlatives: aggregate when no grouping, ranking when grouped ("which region has the highest …").
HIGH_WORDS = {"highest", "largest", "biggest", "most", "best", "greatest", "top"}
LOW_WORDS = {"lowest", "smallest", "least", "fewest", "worst", "bottom"}
COUNT_PHRASES = [("how", "many"), ("number", "of"), ("count", "of"), ("count",), ("headcount",)]
DISTINCT_WORDS = {"unique", "distinct", "different"}
ROW_NOUNS = {"row", "record", "entry", "line", "item", "transaction"}

PERIODS = {
    "day": "day", "daily": "day", "date": "day",
    "week": "week", "weekly": "week",
    "month": "month", "monthly": "month",
    "quarter": "quarter", "quarterly": "quarter",
    "year": "year", "yearly": "year", "annual": "year", "annually": "year",
}
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# Words that carry no meaning for the query shape.
FILLER = {
    "what", "whats", "is", "are", "was", "were", "the", "a", "an", "of", "for", "me", "show", "give", "list",
    "tell", "display", "find", "get", "our", "my", "all", "please", "can", "you", "i", "we", "see", "do",
    "does", "did", "there", "which", "who", "has", "have", "had", "with", "value", "values", "amount",
    "data", "dataset", "file", "sheet", "table", "in", "on", "at", "to", "and", "per", "by", "each", "every",
    "across", "from", "this", "that", "these", "those", "it", "its", "be", "been", "much", "many", "how",
    "number", "count", "rank", "ranked", "ranking", "sorted", "order", "ordered", "breakdown", "split",
    "grouped", "group", "wise", "where", "equal", "equals", "only", "just", "figure", "figures", "trend",
    "over", "time", "period", "so", "far", "up", "as", "well", "sold", "sell", "selling", "had", "made",
}

# Common business synonyms → words that may appear in column names.
SYNONYMS = {
    "sales": {"revenue", "sales", "amount", "turnover"},
    "revenue": {"revenue", "sales", "turnover", "income"},
    "income": {"income", "revenue"},
    "turnover": {"turnover", "revenue", "sales"},
    "profit": {"profit", "margin", "earnings"},
    "earnings": {"earnings", "profit"},
    "spend": {"spend", "cost", "expense", "expenses"},
    "cost": {"cost", "spend", "expense"},
    "expense": {"expense", "cost", "spend"},
    "units": {"units", "quantity", "qty"},
    "quantity": {"quantity", "qty", "units"},
    "qty": {"qty", "quantity", "units"},
    "price": {"price", "unit_price", "rate"},
    "customer": {"customer", "client", "buyer"},
    "client": {"client", "customer"},
    "employee": {"employee", "staff", "name"},
    "salary": {"salary", "pay", "wage", "compensation"},
    "country": {"country", "nation"},
    "city": {"city", "town"},
    "category": {"category", "type", "segment"},
}

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("ses"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _name_tokens(name: str) -> list[str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name))
    return [_singular(t) for t in _TOKEN_RE.findall(spaced.lower())]


def _q(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _lit(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _label(col: str) -> str:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(col))
    return " ".join(_TOKEN_RE.findall(spaced.lower())) or str(col)


@dataclass
class Plan:
    sql: str
    explanation: str
    kind: str
    columns: list[str] = field(default_factory=list)


@dataclass
class _Col:
    name: str
    tokens: list[str]
    numeric: bool
    is_id: bool
    is_date: bool
    date_expr: str | None


# ── Schema analysis ─────────────────────────────────────────────────────────

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _describe_columns(df: pd.DataFrame) -> list[_Col]:
    cols = []
    for name in df.columns:
        series = df[name]
        tokens = _name_tokens(name)
        numeric = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
        is_id = bool({"id", "key", "code", "uuid"} & set(tokens)) or (tokens[-1:] == ["no"])
        date_expr = None
        if pd.api.types.is_datetime64_any_dtype(series):
            date_expr = _q(name)
        elif series.dtype == object:
            sample = series.dropna().astype(str).head(50)
            if len(sample) and sample.map(lambda v: bool(_ISO_DATE.match(v))).mean() >= 0.9:
                date_expr = f"TRY_CAST({_q(name)} AS TIMESTAMP)"
        cols.append(_Col(str(name), tokens, numeric and not is_id, is_id, date_expr is not None, date_expr))
    return cols


def _value_index(df: pd.DataFrame, cols: list[_Col]) -> dict[str, list[tuple[str, str]]]:
    """lower-cased cell value → [(column, original value)] for low-cardinality text columns."""
    index: dict[str, list[tuple[str, str]]] = {}
    for col in cols:
        if col.numeric or col.is_date:
            continue
        series = df[col.name]
        if series.dtype != object and not isinstance(series.dtype, pd.CategoricalDtype):
            continue
        uniques = series.dropna().astype(str).unique()
        if len(uniques) > 500:
            continue
        for value in uniques:
            key = " ".join(_TOKEN_RE.findall(value.lower()))
            if key and not key.isdigit() and key not in FILLER and key not in AGG_WORDS:
                index.setdefault(key, []).append((col.name, value))
    return index


# ── Parsing helpers ─────────────────────────────────────────────────────────

class _Tokens:
    def __init__(self, text: str):
        self.raw = _TOKEN_RE.findall(text.lower().replace("'s", ""))
        self.words = [_singular(t) for t in self.raw]
        self.used = [False] * len(self.words)

    def free(self, i: int) -> bool:
        return 0 <= i < len(self.words) and not self.used[i]

    def take(self, *idx: int) -> None:
        for i in idx:
            self.used[i] = True

    def unused_meaningful(self) -> list[str]:
        return [w for w, u, r in zip(self.words, self.used, self.raw)
                if not u and w not in FILLER and r not in FILLER]


def _match_exact(tokens: _Tokens, cols: list[_Col], min_len: int = 1) -> list[tuple[_Col, list[int]]]:
    """Exact column-name mentions, longest names first."""
    found: list[tuple[_Col, list[int]]] = []
    n = len(tokens.words)
    for col in sorted(cols, key=lambda c: -len(c.tokens)):
        k = len(col.tokens)
        if k < max(min_len, 1):
            continue
        for i in range(n - k + 1):
            span = list(range(i, i + k))
            if all(tokens.free(j) for j in span) and tokens.words[i:i + k] == col.tokens:
                found.append((col, span))
                tokens.take(*span)
                break
    return found


def _match_columns(tokens: _Tokens, cols: list[_Col], want, found=None) -> list[tuple[_Col, list[int]]]:
    """Find column mentions (exact names first, then unique words and synonyms)."""
    candidates = [c for c in cols if want(c)]
    found = list(found or []) + _match_exact(tokens, [c for c in candidates if all(c is not f[0] for f in (found or []))])
    # 2. A single word that uniquely identifies one column (e.g. "revenue" → "total_revenue_usd").
    for i, word in enumerate(tokens.words):
        if not tokens.free(i) or word in FILLER or word in AGG_WORDS:
            continue
        direct = [c for c in candidates if word in c.tokens and all(c is not f[0] for f in found)]
        if len(direct) == 1:
            found.append((direct[0], [i]))
            tokens.take(i)
            continue
        if len(direct) > 1:
            raise _Ambiguous(word)
        syn = SYNONYMS.get(tokens.raw[i]) or SYNONYMS.get(word)
        if syn:
            via = [c for c in candidates if syn & set(c.tokens) and all(c is not f[0] for f in found)]
            if len(via) == 1:
                found.append((via[0], [i]))
                tokens.take(i)
            elif len(via) > 1:
                raise _Ambiguous(word)
    return sorted(found, key=lambda f: f[1][0])


class _Ambiguous(Exception):
    pass


def _period_expr(period: str, expr: str) -> str:
    if period == "quarter":
        return f"CAST(year({expr}) AS VARCHAR) || '-Q' || CAST(quarter({expr}) AS VARCHAR)"
    fmt = {"year": "%Y", "month": "%Y-%m", "week": "%Y-%m-%d", "day": "%Y-%m-%d"}[period]
    return f"strftime(date_trunc('{period}', {expr}), '{fmt}')"


def _find_phrase(tokens: _Tokens, phrase: tuple[str, ...]) -> int | None:
    k = len(phrase)
    for i in range(len(tokens.words) - k + 1):
        if all(tokens.free(i + j) for j in range(k)) and tuple(tokens.raw[i:i + k]) == phrase:
            return i
    return None


# ── Main entry point ────────────────────────────────────────────────────────

def plan_question(question: str, df: pd.DataFrame, table_name: str) -> Plan | None:
    """Return a deterministic SQL plan for ``question`` or ``None`` when unsure."""
    if not question or df is None or df.empty or len(question) > 200:
        return None
    text = question.strip().lower()
    # Phrasings that need reasoning, comparison or prediction go to the AI.
    if re.search(r"\b(why|explain|predict|forecast|correlat\w*|compare|versus|vs|growth|grow\w*|change|difference|"
                 r"ratio|percent\w*|share|proportion|between|than|outlier\w*|anomal\w*|clean|summar\w*|chart|plot|graph|"
                 r"not|without|except|exclude\w*|or|if|should|recommend\w*|insight\w*)\b|%|[<>=]", text):
        return None
    try:
        return _plan(question, df, table_name)
    except _Ambiguous:
        return None


def _plan(question: str, df: pd.DataFrame, table_name: str) -> Plan | None:
    cols = _describe_columns(df)
    t = _Tokens(question)
    if not t.words:
        return None
    table = _q(table_name)

    # ── top / bottom N ───────────────────────────────────────────────────
    limit = None
    rank_dir = None
    for i, raw in enumerate(t.raw):
        if raw in ("top", "bottom", "best", "worst") and t.free(i):
            rank_dir = "DESC" if raw in ("top", "best") else "ASC"
            t.take(i)
            if t.free(i + 1) and t.raw[i + 1].isdigit():
                limit = max(1, min(int(t.raw[i + 1]), 100))
                t.take(i + 1)
            else:
                limit = 10
            break

    # ── time grouping ("by month", "monthly") ───────────────────────────
    period = None
    for i, raw in enumerate(t.raw):
        if raw in PERIODS and t.free(i):
            prev = t.raw[i - 1] if i > 0 else ""
            if raw in ("month", "year", "quarter", "week", "day", "date") and prev not in ("by", "per", "each", "every", "which", "what"):
                continue  # "this year", "a month" → not a grouping
            period = PERIODS[raw]
            t.take(i)
            break

    # Multi-word column names ("revenue 2026", "sales rep") win over value/year parsing.
    pre_cols = _match_exact(t, cols, min_len=2)

    # ── filters: year / month / text values ─────────────────────────────
    filters: list[str] = []
    filter_desc: list[str] = []
    date_cols = [c for c in cols if c.is_date]

    def _date_col() -> _Col | None:
        if len(date_cols) == 1:
            return date_cols[0]
        named = [c for c in date_cols if c.tokens and c.tokens[-1] == "date"]
        return named[0] if len(named) == 1 else None

    for i, raw in enumerate(t.raw):
        if not t.free(i):
            continue
        if re.fullmatch(r"(19|20)\d{2}", raw):
            dc = _date_col()
            if dc is None:
                return None
            filters.append(f"year({dc.date_expr}) = {int(raw)}")
            filter_desc.append(raw)
            t.take(i)
        elif raw in MONTHS and (raw not in ("may", "mar", "dec", "jun", "jul", "oct", "sep") or (i > 0 and t.raw[i - 1] in ("in", "for", "during"))):
            dc = _date_col()
            if dc is None:
                return None
            filters.append(f"month({dc.date_expr}) = {MONTHS[raw]}")
            filter_desc.append(raw.capitalize())
            t.take(i)

    values = _value_index(df, cols)
    n = len(t.words)
    for size in (3, 2, 1):
        for i in range(n - size + 1):
            span = list(range(i, i + size))
            if not all(t.free(j) for j in span):
                continue
            key = " ".join(t.raw[i:i + size])
            hits = values.get(key)
            if not hits:
                continue
            if len({c for c, _ in hits}) > 1:
                return None  # the same value appears in several columns
            col_name, original = hits[0]
            filters.append(f"{_q(col_name)} = {_lit(original)}")
            filter_desc.append(original)
            t.take(*span)
            # "in the West region" → the column word is part of the filter, not a grouping.
            col_tokens = next(c.tokens for c in cols if c.name == col_name)
            for j in (i - 1, i + size):
                if t.free(j) and t.words[j] in col_tokens:
                    t.take(j)

    # ── aggregation words ───────────────────────────────────────────────
    agg = None
    distinct = False
    count = False
    for phrase in COUNT_PHRASES:
        pos = _find_phrase(t, phrase)
        if pos is not None:
            count = True
            t.take(*range(pos, pos + len(phrase)))
            break
    for i, raw in enumerate(t.raw):
        if not t.free(i):
            continue
        if raw in DISTINCT_WORDS:
            distinct = True
            t.take(i)
        elif raw in AGG_WORDS and agg is None:
            agg = AGG_WORDS[raw]
            t.take(i)
        elif raw in HIGH_WORDS | LOW_WORDS and agg is None and rank_dir is None:
            rank_dir = "DESC" if raw in HIGH_WORDS else "ASC"
            t.take(i)

    # ── columns ─────────────────────────────────────────────────────────
    mentioned = _match_columns(t, cols, lambda c: not c.is_date or period is None, found=pre_cols)
    measures = [c for c, _ in mentioned if c.numeric]
    dims = [c for c, _ in mentioned if not c.numeric]

    # Row nouns ("how many orders", "number of records")
    row_noun = False
    for i, w in enumerate(t.words):
        if t.free(i) and w in ROW_NOUNS:
            row_noun = True
            t.take(i)

    if t.unused_meaningful():
        return None  # something we don't understand → let the AI handle it

    group_col: _Col | None = None
    group_expr = group_label = None
    if period:
        dc = _date_col()
        if dc is None:
            return None
        group_expr = _period_expr(period, dc.date_expr)
        group_label = period
        filters.append(f"{dc.date_expr} IS NOT NULL")
    elif dims:
        if count and len(dims) == 1 and dims[0].is_id and not rank_dir:
            group_col = None  # "how many orders" with order_id → count distinct ids below
        elif count and len(dims) == 2 and sum(d.is_id for d in dims) == 1:
            # "number of employees by department" → COUNT(DISTINCT employee_id) per department
            group_col = next(d for d in dims if not d.is_id)
            group_expr = _q(group_col.name)
            group_label = _label(group_col.name)
        else:
            if len(dims) > 1:
                return None
            group_col = dims[0]
            group_expr = _q(group_col.name)
            group_label = _label(group_col.name)

    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    flt = f" for {', '.join(filter_desc)}" if filter_desc else ""

    # ── COUNT questions ─────────────────────────────────────────────────
    if row_noun and not count and not measures:
        if filters and not agg and not rank_dir and not group_expr:
            return Plan(f"SELECT * FROM {table}{where} LIMIT 100", f"Rows{flt}.", "rows", [])
        return None  # "show me the rows" etc. — not an aggregate question
    if count:
        if measures:
            return None
        id_dims = [d for d in dims if d.is_id]
        if id_dims and (group_col is None or group_col is not id_dims[0]):
            expr = f"COUNT(DISTINCT {_q(id_dims[0].name)})"
            what = f"distinct {_label(id_dims[0].name)} values"
            if group_col is None and not group_expr:
                return Plan(f"SELECT {expr} AS count FROM {table}{where}", f"Number of {what}{flt}.", "count",
                            [id_dims[0].name])
        elif distinct and group_col is not None and not period and not rank_dir:
            expr = f"COUNT(DISTINCT {_q(group_col.name)})"
            what = f"distinct {group_label} values"
            return Plan(f"SELECT {expr} AS count FROM {table}{where}",
                        f"Number of {what}{flt}.", "count", [group_col.name])
        else:
            expr = "COUNT(*)"
            what = "rows"
        if group_expr:
            if period and not rank_dir:
                order, lim = "1", ""
            else:
                order = f"2 {rank_dir or 'DESC'}"
                lim = f" LIMIT {limit or (1 if rank_dir else 100)}"
            sql = (f"SELECT {group_expr} AS {_q(group_label)}, {expr} AS count FROM {table}{where} "
                   f"GROUP BY 1 ORDER BY {order}{lim}")
            return Plan(sql, f"Number of {what} for each {group_label}{flt}.", "count_by", [c.name for c, _ in mentioned])
        if rank_dir:
            return None
        return Plan(f"SELECT {expr} AS count FROM {table}{where}", f"Number of {what}{flt}.", "count",
                    [c.name for c, _ in mentioned])

    # ── Aggregate / rank questions ──────────────────────────────────────
    if len(measures) != 1:
        if not measures and row_noun:
            return None
        if not measures and filters and not agg and not rank_dir and not group_expr:
            return Plan(f"SELECT * FROM {table}{where} LIMIT 100", f"Rows{flt}.", "rows", [])
        return None
    measure = measures[0]
    m = _q(measure.name)
    m_label = _label(measure.name)
    is_float = pd.api.types.is_float_dtype(df[measure.name])

    if group_expr is None:
        if rank_dir and not agg:
            agg = "max" if rank_dir == "DESC" else "min"
            rank_dir = None
            if limit:
                return None
        if rank_dir:
            return None
        func = {"sum": "SUM", "avg": "AVG", "median": "MEDIAN", "max": "MAX", "min": "MIN"}[agg or "sum"]
        value = f"ROUND({func}({m}), 2)" if func in ("AVG", "MEDIAN") or is_float else f"{func}({m})"
        name = f"{(agg or 'total').replace('sum', 'total').replace('avg', 'average')}_{measure.name.lower()}"
        word = {"sum": "Total", "avg": "Average", "median": "Median", "max": "Highest", "min": "Lowest"}[agg or "sum"]
        return Plan(f"SELECT {value} AS {_q(name)} FROM {table}{where}",
                    f"{word} {m_label}{flt}.", "aggregate", [measure.name])

    func = {"sum": "SUM", "avg": "AVG", "median": "MEDIAN", "max": "MAX", "min": "MIN", None: "SUM"}[agg]
    value = f"ROUND({func}({m}), 2)" if func in ("AVG", "MEDIAN") or is_float else f"{func}({m})"
    alias = {"SUM": "total", "AVG": "average", "MEDIAN": "median", "MAX": "max", "MIN": "min"}[func] + "_" + measure.name.lower()
    word = {"SUM": "Total", "AVG": "Average", "MEDIAN": "Median", "MAX": "Highest", "MIN": "Lowest"}[func]
    used = [measure.name] + ([group_col.name] if group_col else [])

    if period:
        if rank_dir:
            direction = rank_dir
            lim = limit or 1
            sql = (f"SELECT {group_expr} AS {_q(group_label)}, {value} AS {_q(alias)} FROM {table}{where} "
                   f"GROUP BY 1 ORDER BY 2 {direction} LIMIT {lim}")
            best = "highest" if direction == "DESC" else "lowest"
            expl = (f"The {period} with the {best} {word.lower()} {m_label}{flt}." if lim == 1
                    else f"The {lim} {period}s with the {best} {word.lower()} {m_label}{flt}.")
            return Plan(sql, expl, "rank_period", used)
        sql = (f"SELECT {group_expr} AS {_q(group_label)}, {value} AS {_q(alias)} FROM {table}{where} "
               f"GROUP BY 1 ORDER BY 1")
        return Plan(sql, f"{word} {m_label} for each {period}{flt}, in date order.", "trend", used)

    direction = rank_dir or "DESC"
    lim = limit or (1 if rank_dir else 100)
    sql = (f"SELECT {group_expr} AS {_q(group_label)}, {value} AS {_q(alias)} FROM {table}{where} "
           f"GROUP BY 1 ORDER BY 2 {direction} LIMIT {lim}")
    if rank_dir and not limit:
        expl = f"The {group_label} with the {'highest' if direction == 'DESC' else 'lowest'} {word.lower()} {m_label}{flt}."
    elif rank_dir:
        expl = (f"The {lim} {group_label} groups with the {'highest' if direction == 'DESC' else 'lowest'} "
                f"{word.lower()} {m_label}{flt}.")
    else:
        expl = f"{word} {m_label} for each {group_label}{flt}, highest first."
    return Plan(sql, expl, "group", used)
