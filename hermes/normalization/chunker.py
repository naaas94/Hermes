"""Context-window-aware chunker for normalized Markdown pages."""

from __future__ import annotations

from hermes.config import load_config
from hermes.models import Chunk, NormalizedPage

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def chunk_pages(
    pages: list[NormalizedPage],
    context_window: int | None = None,
    overlap_ratio: float | None = None,
) -> list[Chunk]:
    """Split or merge normalized pages into LLM-sized chunks.

    - Pages that exceed the context window are split with overlap.
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

    # Reserve ~20% of context window for system prompt + schema + response
    usable_tokens = int(context_window * 0.8)

    raw_segments: list[tuple[str, list[int]]] = []
    for page in pages:
        text = page.markdown_path.read_text(encoding="utf-8")
        tokens = estimate_tokens(text)

        if tokens <= usable_tokens:
            raw_segments.append((text, [page.page_index]))
        else:
            splits = _split_text(text, usable_tokens, overlap_ratio)
            for s in splits:
                raw_segments.append((s, [page.page_index]))

    chunks = _merge_segments(raw_segments, usable_tokens)
    return chunks


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
