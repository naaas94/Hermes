"""Evaluation subsystem (fixtures, manifests, scoring)."""

from hermes.eval.manifest import (
    ChunkExpectation,
    ChunkLabel,
    EvalManifest,
    PageRange,
    load_manifest,
)
from hermes.eval.scorer import (
    ChunkReason,
    ChunkScore,
    EvalResult,
    EvalSummary,
    FieldDiff,
    FieldMatch,
)

__all__ = [
    "ChunkExpectation",
    "ChunkLabel",
    "ChunkReason",
    "ChunkScore",
    "EvalManifest",
    "EvalResult",
    "EvalSummary",
    "FieldDiff",
    "FieldMatch",
    "PageRange",
    "load_manifest",
]
