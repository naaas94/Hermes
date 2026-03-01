"""Core Pydantic models used across Hermes."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class FileType(str, Enum):
    EXCEL = "excel"
    PDF_TEXT = "pdf_text"
    PDF_SCANNED = "pdf_scanned"
    UNKNOWN = "unknown"


class JobStatus(str, Enum):
    QUEUED = "queued"
    NORMALIZING = "normalizing"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class DLQStatus(str, Enum):
    PENDING = "pending"
    REPLAYED = "replayed"
    ABANDONED = "abandoned"


class PreflightResult(BaseModel):
    file_type: FileType
    page_count: int = 0
    has_text_layer: bool = False
    estimated_tokens: int = 0
    file_name: str = ""
    file_size_bytes: int = 0


class NormalizedPage(BaseModel):
    page_index: int
    markdown_path: Path
    source_type: FileType
    char_count: int = 0


class Chunk(BaseModel):
    chunk_index: int
    text: str
    source_pages: list[int] = Field(default_factory=list)
    estimated_tokens: int = 0


class LLMResponse(BaseModel):
    content: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    raw_response: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    id: str
    file_name: str
    file_type: FileType
    page_count: int = 0
    has_text_layer: bool = False
    schema_class: str = ""
    normalization_error: str = ""
    status: JobStatus = JobStatus.QUEUED
    total_chunks: int = 0
    completed_chunks: int = 0
    failed_chunks: int = 0
    created_at: datetime | None = None
    completed_at: datetime | None = None


class ExtractionResult(BaseModel):
    id: int | None = None
    job_id: str
    chunk_index: int
    source_pages: str = ""
    record_json: str = ""
    model: str = ""
    prompt_version: str = ""
    created_at: datetime | None = None


class LLMRun(BaseModel):
    id: int | None = None
    job_id: str
    chunk_index: int
    run_type: str = "extraction"
    model: str = ""
    prompt_version: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    total_latency_ms: int = 0
    validation_passed: bool = False
    validation_error: str = ""
    raw_output: str = ""
    created_at: datetime | None = None


class PipelineStage(BaseModel):
    id: int | None = None
    job_id: str
    stage: str
    started_at: str = ""
    ended_at: str = ""
    duration_ms: int = 0
    detail: str = ""
    created_at: datetime | None = None


class FailedExtraction(BaseModel):
    id: int | None = None
    job_id: str
    chunk_index: int
    chunk_text_uri: str = ""
    last_error: str = ""
    retry_count: int = 0
    status: DLQStatus = DLQStatus.PENDING
    created_at: datetime | None = None
