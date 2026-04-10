"""Parse and validate --pages (1-based PDF page / Excel sheet selection)."""

from __future__ import annotations


def parse_pages_spec(spec: str | None) -> frozenset[int] | None:
    """Parse a pages argument into 1-based indices, or None if unset/empty (process all).

    Supported forms: ``1-10`` (inclusive range), ``3,5,7`` (discrete pages),
    and combinations like ``1,3-5,10``. Whitespace around commas and ranges is ignored.
    """
    if spec is None:
        return None
    s = spec.strip()
    if not s:
        return None

    out: set[int] = set()
    for raw_part in s.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            left, _, right = part.partition("-")
            try:
                a = int(left.strip())
                b = int(right.strip())
            except ValueError as e:
                raise ValueError(f"Invalid page range: {part!r}") from e
            if a < 1 or b < 1:
                raise ValueError("Page numbers must be at least 1 (1-based).")
            if b < a:
                raise ValueError(f"Invalid range {part!r}: end must be >= start.")
            out.update(range(a, b + 1))
        else:
            try:
                n = int(part)
            except ValueError as e:
                raise ValueError(f"Invalid page number: {part!r}") from e
            if n < 1:
                raise ValueError("Page numbers must be at least 1 (1-based).")
            out.add(n)

    if not out:
        raise ValueError("Page selection is empty.")
    return frozenset(out)


def validate_pages_against_total(selection_1based: frozenset[int], total: int) -> None:
    """Ensure every selected page is in 1..total (inclusive)."""
    if total < 1:
        raise ValueError("Document has no pages or sheets to select.")
    bad = [p for p in selection_1based if p < 1 or p > total]
    if bad:
        b = min(bad)
        raise ValueError(
            f"Page {b} is out of range; this document has {total} page(s) "
            f"or sheet(s) (use indices 1-{total})."
        )


def resolve_page_indices_0(
    pages_spec: str | None, total_pages: int
) -> frozenset[int] | None:
    """Return None to process everything, or 0-based indices to normalize/extract.

    ``total_pages`` is the PDF page count or Excel sheet count from preflight.
    """
    sel = parse_pages_spec(pages_spec)
    if sel is None:
        return None
    validate_pages_against_total(sel, total_pages)
    return frozenset(p - 1 for p in sel)
