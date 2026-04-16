"""Field-value normalization for golden vs actual comparison (eval scorer)."""

from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

logger = logging.getLogger("hermes.eval.normalize")

MatchType = Literal["exact", "normalized", "mismatch", "missing"]

# Default tolerances aligned with ``math.isclose`` defaults.
DEFAULT_REL_TOL = 1e-9
DEFAULT_ABS_TOL = 0.0

_CURRENCY_STRIP_RE = re.compile(r"[$€£¥\s]")
_THOUSANDS_RE = re.compile(r",(?=\d{3}(\D|$))")


def normalize_string(v: Any) -> str:
    """Lowercase (Unicode casefold), strip leading/trailing whitespace."""
    s = v if isinstance(v, str) else str(v)
    return s.casefold().strip()


def numbers_close(a: Any, b: Any, rel_tol: float = DEFAULT_REL_TOL, abs_tol: float = DEFAULT_ABS_TOL) -> bool:
    """Whether two numeric values are close using ``math.isclose`` semantics."""
    try:
        fa = float(Decimal(str(a)))
        fb = float(Decimal(str(b)))
    except (InvalidOperation, ValueError, TypeError):
        return False
    if math.isnan(fa) or math.isnan(fb):
        return math.isnan(fa) and math.isnan(fb)
    return math.isclose(fa, fb, rel_tol=rel_tol, abs_tol=abs_tol)


def _try_parse_iso_datetime(s: str) -> datetime | None:
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        return None


def _try_parse_date_patterns(s: str) -> date | None:
    t = s.strip()
    if not t:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(t, fmt)
            return dt.date()
        except ValueError:
            continue
    return None


def _iso_from_parsed_string(original: str, iso_dt: datetime) -> str:
    """Prefer date-only ISO when the input string has no time component."""
    st = original.strip()
    if len(st) <= 10 and "T" not in st.upper():
        return iso_dt.date().isoformat()
    return iso_dt.isoformat(timespec="seconds")


def normalize_date(v: Any) -> str | None:
    """Parse a date/datetime-like value and return a canonical ISO string, or ``None`` if unknown."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if not isinstance(v, str):
        return normalize_date(str(v))
    s = v.strip()
    if not s:
        return None
    iso_dt = _try_parse_iso_datetime(s)
    if iso_dt is not None:
        return _iso_from_parsed_string(s, iso_dt)
    d = _try_parse_date_patterns(s)
    if d is not None:
        return d.isoformat()
    logger.debug("normalize_date could not parse value=%r", v)
    return None


def _strip_currency_thousands(s: str) -> str:
    """Remove currency symbols/spaces and thousands separators (commas between digit groups)."""
    t = _CURRENCY_STRIP_RE.sub("", s)
    t = _THOUSANDS_RE.sub("", t)
    return t


def parse_currency_value(v: Any) -> float | None:
    """Parse a currency-like string or number into a float."""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if not isinstance(v, str):
        return parse_currency_value(str(v))
    t = _strip_currency_thousands(v.strip())
    if not t:
        return None
    try:
        return float(Decimal(t))
    except (InvalidOperation, ValueError):
        return None


def parse_percent_value(v: Any) -> float | None:
    """Parse ``5%``, ``0.05``, or numeric strings into a fraction (0–1 scale)."""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        x = float(v)
        if -1.0 <= x <= 1.0:
            return x
        if 0.0 < x <= 100.0:
            return x / 100.0
        return x
    if not isinstance(v, str):
        return parse_percent_value(str(v))
    t = v.strip()
    if not t:
        return None
    if t.endswith("%"):
        try:
            return float(Decimal(t[:-1].strip())) / 100.0
        except (InvalidOperation, ValueError):
            return None
    try:
        x = float(Decimal(t))
    except (InvalidOperation, ValueError):
        return None
    if -1.0 <= x <= 1.0:
        return x
    if 0.0 < x <= 100.0:
        return x / 100.0
    return x


def _parse_plain_number(x: Any) -> float | None:
    """Parse ints/floats or plain numeric strings (not currency or percent)."""
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    if not isinstance(x, str):
        return None
    t = x.strip()
    if not t or t.endswith("%"):
        return None
    if any(sym in t for sym in ("$", "€", "£", "¥")):
        return None
    t = t.replace(",", "")
    try:
        return float(Decimal(t))
    except (InvalidOperation, ValueError):
        return None


def _is_absent(x: Any) -> bool:
    if x is None:
        return True
    if isinstance(x, str) and not x.strip():
        return True
    return False


def _both_absent(a: Any, b: Any) -> bool:
    return _is_absent(a) and _is_absent(b)


def _number_match_kind(expected: Any, actual: Any) -> MatchType | None:
    fe, fa = _parse_plain_number(expected), _parse_plain_number(actual)
    if fe is None or fa is None:
        return None
    if not numbers_close(fe, fa):
        return "mismatch"
    return "exact" if fe == fa else "normalized"


def normalize_value(expected: Any, actual: Any, field_type_hint: str | None = None) -> MatchType:
    """
    Compare expected vs actual with optional type hint.

    ``field_type_hint``: ``None`` (lenient auto), or ``string``, ``number``, ``currency``,
    ``percent``, ``date``, ``strict`` (no normalization — equality only).
    """
    hint = (field_type_hint or "").strip().casefold() or None

    if hint == "strict":
        if _both_absent(expected, actual):
            return "exact"
        if _is_absent(actual) and not _is_absent(expected):
            return "missing"
        if not _is_absent(actual) and _is_absent(expected):
            return "mismatch"
        return "exact" if expected == actual else "mismatch"

    if _both_absent(expected, actual):
        return "exact"
    if _is_absent(actual) and not _is_absent(expected):
        return "missing"
    if not _is_absent(actual) and _is_absent(expected):
        return "mismatch"

    if hint in ("number", None):
        mk = _number_match_kind(expected, actual)
        if mk is not None:
            return mk
        if hint == "number":
            return "mismatch"

    if hint in ("currency", None):
        pe, pa = parse_currency_value(expected), parse_currency_value(actual)
        if pe is not None and pa is not None and numbers_close(pe, pa):
            return "exact" if pe == pa else "normalized"

    if hint in ("percent", None):
        pe, pa = parse_percent_value(expected), parse_percent_value(actual)
        if pe is not None and pa is not None and numbers_close(pe, pa):
            return "exact" if pe == pa else "normalized"

    if hint in ("date", None):
        de, da = normalize_date(expected), normalize_date(actual)
        if de is not None and da is not None and de == da:
            se = expected if isinstance(expected, str) else str(expected)
            sa = actual if isinstance(actual, str) else str(actual)
            return "exact" if se.strip() == sa.strip() else "normalized"
        if hint == "date" and (de is None or da is None):
            return "mismatch"

    if hint == "string":
        raw_e = expected if isinstance(expected, str) else str(expected)
        raw_a = actual if isinstance(actual, str) else str(actual)
        if raw_e == raw_a:
            return "exact"
        if normalize_string(raw_e) == normalize_string(raw_a):
            return "normalized"
        return "mismatch"

    raw_e = expected if isinstance(expected, str) else str(expected)
    raw_a = actual if isinstance(actual, str) else str(actual)
    if raw_e == raw_a:
        return "exact"
    if normalize_string(raw_e) == normalize_string(raw_a):
        return "normalized"
    return "mismatch"
