"""Context-window-aware chunker for normalized Markdown pages."""

from __future__ import annotations

import re

from hermes.config import load_config
from hermes.models import Chunk, NormalizedPage

CHARS_PER_TOKEN = 2

# Table chunks: cap rows so LLM output stays small
MAX_TABLE_ROWS_PER_CHUNK = 10
# Max tokens for a table chunk (input); keeps output generation within timeout on small GPUs.
MAX_TABLE_CHUNK_TOKENS = 2500
# Cap for non-table (e.g. PDF) chunks so input + system/schema leaves room for full JSON output.
# Without this, 0.3 * large context (e.g. 128k) allows ~38k-token chunks and output gets cut off.
MAX_TEXT_CHUNK_TOKENS = 2048


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def _is_table_line(ln: str) -> bool:
    return bool(re.match(r"^\|.+\|$", ln))


def _is_separator_line(ln: str) -> bool:
    """True if line is a markdown table separator (| --- | --- | ...), i.e. pipe-line with no letters."""
    return _is_table_line(ln) and not re.search(r"[a-zA-Z]", ln)


def _is_table_content(text: str) -> bool:
    """True if content looks like markdown tables (majority of lines are table rows)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 10:
        return False
    table_like = sum(
        1 for ln in lines if _is_table_line(ln) and not _is_separator_line(ln)
    )
    return table_like >= 0.5 * len(lines)


def _split_table_by_rows(
    text: str, max_data_rows: int, page_index: int
) -> list[tuple[str, list[int]]]:
    """Split markdown table content into chunks of at most max_data_rows data rows each.
    Preserves header + separator at the start of each chunk.
    """
    lines = text.splitlines()
    # Find first header and separator (separator = pipe-line with only ---/spaces, no letters)
    header_line: str | None = None
    sep_line: str | None = None
    data_start = 0

    for i, ln in enumerate(lines):
        if not _is_table_line(ln):
            continue
        if _is_separator_line(ln):
            if header_line is not None:
                sep_line = ln
                data_start = i + 1
                break
        else:
            if header_line is None:
                header_line = ln

    if header_line is None or sep_line is None or data_start >= len(lines):
        # Not a recognizable table; fall back to one segment
        return [(text, [page_index])]

    # Collect all data rows (pipe-lines that aren't the separator).
    # Skip blank lines (normalizer inserts them between table blocks); only stop on real content.
    data_rows: list[str] = []
    for i in range(data_start, len(lines)):
        ln = lines[i]
        if _is_table_line(ln) and not _is_separator_line(ln):
            data_rows.append(ln)
        elif data_rows and ln.strip() and not _is_table_line(ln):
            # Non-table content line (e.g. heading) — stop to keep table blocks intact
            break

    if not data_rows:
        return [(text, [page_index])]

    # Optional: include any leading non-table content (e.g. "# Sheet1") before first chunk
    prefix_lines = lines[: data_start - 2] if data_start >= 2 else []
    prefix = "\n".join(prefix_lines) + "\n\n" if prefix_lines else ""

    segments: list[tuple[str, list[int]]] = []
    for start in range(0, len(data_rows), max_data_rows):
        block = data_rows[start : start + max_data_rows]
        chunk_text = prefix + header_line + "\n" + sep_line + "\n" + "\n".join(block) + "\n"
        segments.append((chunk_text, [page_index]))
        prefix = ""  # only first chunk gets the title prefix

    return segments


def chunk_pages(
    pages: list[NormalizedPage],
    context_window: int | None = None,
    overlap_ratio: float | None = None,
) -> list[Chunk]:
    """Split or merge normalized pages into LLM-sized chunks.

    - Pages that exceed the context window are split with overlap.
    - Table-heavy content is split by row count (max MAX_TABLE_ROWS_PER_CHUNK) so
      LLM output stays small and within timeout.
    - Small consecutive pages are merged until they'd exceed the window.
    - Each page file is read from disk one at a time (memory-safe).
    """
    cfg = load_config()
    if context_window is None:
        if cfg.llm.provider == "litellm":
            context_window = cfg.llm.litellm.context_window_tokens
        else:
            context_window = cfg.llm.context_window_tokens
    if overlap_ratio is None:
        overlap_ratio = cfg.extraction.chunk_overlap_ratio

    # Reserve ~% of context window for system prompt + schema + response.
    # Cap at MAX_TEXT_CHUNK_TOKENS so PDF chunks don't consume the whole window and truncate output.
    usable_tokens = min(int(context_window * 0.3), MAX_TEXT_CHUNK_TOKENS)

    mergeable_segments: list[tuple[str, list[int]]] = []
    table_segments: list[tuple[str, list[int]]] = []

    for page in pages:
        text = page.markdown_path.read_text(encoding="utf-8")
        tokens = estimate_tokens(text)

        if tokens <= usable_tokens:
            mergeable_segments.append((text, [page.page_index]))
        else:
            if _is_table_content(text):
                table_segments.extend(
                    _split_table_by_rows(text, MAX_TABLE_ROWS_PER_CHUNK, page.page_index)
                )
            else:
                splits = _split_text(text, usable_tokens, overlap_ratio)
                for s in splits:
                    mergeable_segments.append((s, [page.page_index]))

    chunks_from_merge = _merge_segments(mergeable_segments, usable_tokens)
    base_idx = len(chunks_from_merge)
    table_chunks = [
        Chunk(
            chunk_index=base_idx + i,
            text=seg[0],
            source_pages=seg[1],
            estimated_tokens=estimate_tokens(seg[0]),
        )
        for i, seg in enumerate(table_segments)
    ]
    return chunks_from_merge + table_chunks


def _split_text(text: str, max_tokens: int, overlap_ratio: float) -> list[str]:
    """Split a large text into overlapping chunks."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    overlap_chars = int(max_chars * overlap_ratio)
    step = max_chars - overlap_chars
    if step <= 0:
        step = max_chars

    parts: list[str] = []
    start = 0
    while start < len(text):
        end = start + max_chars
        parts.append(text[start:end])
        start += step

    return parts


def _merge_segments(
    segments: list[tuple[str, list[int]]], max_tokens: int
) -> list[Chunk]:
    """Merge small consecutive segments until they'd exceed the token budget."""
    chunks: list[Chunk] = []
    current_text = ""
    current_pages: list[int] = []
    current_tokens = 0
    chunk_idx = 0

    for text, page_ids in segments:
        seg_tokens = estimate_tokens(text)

        if current_tokens + seg_tokens > max_tokens and current_text:
            chunks.append(Chunk(
                chunk_index=chunk_idx,
                text=current_text,
                source_pages=current_pages,
                estimated_tokens=current_tokens,
            ))
            chunk_idx += 1
            current_text = ""
            current_pages = []
            current_tokens = 0

        current_text += ("\n\n" if current_text else "") + text
        current_pages.extend(p for p in page_ids if p not in current_pages)
        current_tokens += seg_tokens

    if current_text:
        chunks.append(Chunk(
            chunk_index=chunk_idx,
            text=current_text,
            source_pages=current_pages,
            estimated_tokens=current_tokens,
        ))

    return chunks
