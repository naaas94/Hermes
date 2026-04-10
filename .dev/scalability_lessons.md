# Scalability Lessons: Hermes as a Teaching System

A concrete, pattern-based guide to backend scalability using the Hermes codebase—what it does well, where it falls short, and the engineering patterns every backend should consider.

---

## Part 1: What Scalability Means for a Backend

**Scalability** = the system keeps behaving well (latency, throughput, correctness) as **load** (requests, data size, concurrency) or **resources** (machines, cores) change.

- **Scale up (vertical):** Same design, bigger machine. Often hits a ceiling (single DB, single process).
- **Scale out (horizontal):** More instances, more workers. Requires design that allows parallelism and avoids single points of contention.

The key question: *What gets worse first when load or size grows?* That is your **bottleneck**. Scalable design is about knowing and managing bottlenecks.

---

## Part 2: What Hermes Does Well (Examples in the System)

### 2.1 Bounded Concurrency

Concurrency is capped so the system doesn’t overload I/O or the LLM.

**In Hermes** (`hermes/extraction/pipeline.py`):

```python
if max_workers > 1:
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_chunk = {
            executor.submit(_process_chunk, ...): chunk for chunk in chunks
        }
```

`--workers` (e.g. 4) caps how many chunks run at once. **Pattern:** Concurrency should be **bounded** and configurable; unbounded concurrency is a common scalability bug.

---

### 2.2 Chunking: Controlling Unit of Work and Memory

Chunking turns one large unit into many small, uniform units that can be processed in parallel and fit in memory.

**In Hermes** (`hermes/normalization/chunker.py`):

- **Split** when a page exceeds token/row limits.
- **Merge** when pages are small so you don’t send tiny chunks.
- **Cap** size (`MAX_TEXT_CHUNK_TOKENS`, `MAX_TABLE_ROWS_PER_CHUNK`) so no single chunk dominates time or memory.

**Pattern:** Define a **bounded unit of work** (chunk size, batch size). That’s the basis for parallelization and predictable resource use.

---

### 2.3 Streaming / Bounded I/O

Hermes streams file copy with a fixed buffer instead of loading the whole file.

**In Hermes** (`hermes/ingestion/storage.py`):

```python
COPY_BUFFER = 8192
shutil.copyfileobj(src, dst, length=COPY_BUFFER)
```

Memory use stays constant regardless of file size. **Pattern:** For large data, prefer **streaming or fixed-buffer I/O** instead of loading entire payloads into memory.

---

### 2.4 Progress Persistence (Per-Item Commits)

Results are persisted after each chunk so a crash doesn’t lose all progress. Trade-off: many small commits can become a bottleneck under high write concurrency (see Part 3).

---

### 2.5 WAL Mode for SQLite

**In Hermes** (`hermes/db.py`):

```python
conn.execute("PRAGMA journal_mode=WAL")
```

WAL allows one writer and **multiple concurrent readers** without blocking the writer as much as the default rollback journal. **Pattern:** Choose storage settings that match your read/write pattern.

---

## Part 3: Gaps and Issues in Hermes (and Remediation)

### 3.1 No Connection Pooling

**Where:** Each chunk opens and closes its own DB connection (`get_connection()` in `_process_chunk`, then `conn.close()`). With many workers and chunks this causes connection churn and more file descriptors.

**Remediation:** Reuse a small number of connections (e.g. one per worker or a tiny pool) instead of one per chunk.

---

### 3.2 Write Amplification: Commit per Insert

**Where:** Every `save_result`, `save_llm_run`, `save_pipeline_stage` does an immediate `conn.commit()`. With multiple workers and frequent `update_job_status` on the main thread, WAL still serializes commits and lock contention grows.

**Remediation:** Batch inserts (e.g. collect LLM runs/results and commit every N chunks or per worker), or update job status every K chunks instead of every chunk.

---

### 3.3 No Retries or Backoff in the LLM Client

**Where:** `OllamaClient` and `LiteLLMClient` do one request and `raise_for_status()` on failure. Under higher `--workers`, rate limits (429) or transient errors cause immediate chunk failure.

**Remediation:** Retry with exponential backoff (and optionally respect `Retry-After` for 429) so transient failures don’t cap scalability.

---

### 3.4 Sequential File Processing in `extract`

**Where:** The CLI loops over files and calls `run_pipeline()` one at a time. Many files ⇒ many sequential pipelines; only within-file chunk parallelism exists.

**Remediation:** Process multiple files in parallel (e.g. a small pool of workers each running `run_pipeline` on the next file), with a global cap on total concurrency.

---

### 3.5 Retry Command Is Fully Sequential

**Where:** The `retry` command replays failed chunks in a single `for fail in failures:` loop with one LLM call per iteration. Many DLQ items ⇒ long wall time.

**Remediation:** Use the same bounded pool pattern as the main pipeline (e.g. `ThreadPoolExecutor`) over the failures list.

---

### 3.6 Config Cached Forever

**Where:** `load_config()` is wrapped with `@functools.lru_cache(maxsize=1)`. Changing `config.toml` has no effect until process restart.

**Remediation:** Remove cache for short-lived CLI, or add TTL / explicit reload for long-running processes.

---

### 3.7 Export Loads All Results Into Memory

**Where:** `export_results_as_records()` loads all rows for a job and parses JSON into one list. Very large jobs can spike memory.

**Remediation:** Use a generator/iterator that yields records (or small batches) and stream to CSV/NDJSON instead of building a full list.

---

## Part 4: SWE / Engineering Scalability Patterns (Reference)

Patterns a backend system **should** consider; use this as a checklist and mental model.

| Pattern | What it means | Hermes |
|--------|----------------|--------|
| **Identify the bottleneck** | Know what limits you (CPU, DB, LLM, disk). Don’t add workers where the resource is already saturated. | Chunk parallelism ✓; DB commits and connection churn are bottlenecks. |
| **Bound concurrency** | Cap threads/workers/connections so you don’t overload a shared resource. | `ThreadPoolExecutor(max_workers=...)` ✓. |
| **Batch when you can** | Group small writes/reads to reduce round-trips and commits. | Not done; one commit per insert. |
| **Stream when you must** | Avoid loading unbounded data into memory; use buffers/iterators. | `save_raw` with buffer ✓; export could stream. |
| **Retry + backoff** | Transient failures (network, 429) should be retried with backoff. | Not in LLM client. |
| **Pool shared resources** | Reuse DB connections (and similar) instead of open/close per task. | No pooling; one conn per chunk. |
| **Back pressure / rate limiting** | Don’t send more load than the slowest stage can handle. | Only via `--workers`; no explicit LLM rate limiter. |
| **Idempotency** | Retrying the same chunk/job should be safe (overwrite or upsert). | Retry overwrites/updates same chunk ✓. |
| **Observability** | Metrics/logs for latency, throughput, errors to see bottlenecks. | Pipeline stages and `llm_runs` help; could add more. |

---

### 4.1 Core Patterns in More Detail

**Bounded concurrency**  
- Use a fixed-size pool (threads, processes, or async tasks) and a queue of work.  
- Prevents thundering herd and respects downstream limits (DB, APIs).

**Batching**  
- Combine many small operations into fewer larger ones (e.g. bulk inserts, batch API calls).  
- Reduces round-trips, lock acquisitions, and commit frequency.

**Streaming / chunked I/O**  
- Process data in fixed-size chunks or via iterators/generators.  
- Keeps memory and latency predictable for large inputs/outputs.

**Retry with backoff**  
- Retry transient failures (network, 5xx, 429) with exponential (or capped) backoff.  
- Optionally respect `Retry-After` and circuit-break after N failures.

**Connection pooling**  
- Reuse a small set of connections (DB, HTTP) instead of creating one per request.  
- Lowers overhead and avoids exhausting connection limits.

**Back pressure**  
- When a stage is slow, slow down or block the producer (e.g. bounded queue, rate limiter).  
- Prevents unbounded queues and OOM.

**Idempotency**  
- Design operations so repeating them (e.g. retry, replay) has the same effect.  
- Use stable keys, upserts, or “last write wins” where appropriate.

**Stateless workers**  
- Prefer workers that don’t hold critical state so you can add/remove them and retry elsewhere.  
- State in DB or shared store; workers are replaceable.

**Horizontal scaling readiness**  
- Avoid single-point bottlenecks (single DB writer, single queue consumer) or plan to shard/partition.  
- Prefer stateless APIs and externalized state (DB, cache, queue).

---

### 4.2 Cementing the Mental Model

- **Concrete:** Run `extract` with 1 vs 4 workers; add retries in the LLM client and observe fewer hard failures; change config mid-run and see it ignored.  
- **Abstract:** Name each change: “bounded concurrency,” “batching,” “connection reuse.”  
- **Relate to Hermes:** For “we need to scale,” ask: more files? → parallelize file loop. More chunks? → already parallel; watch DB and LLM. Bigger files? → chunking and streaming help; watch normalize/chunk (single-threaded).

---

## Summary

**Scalability** = know your bottleneck, bound concurrency, batch or stream I/O as appropriate, pool expensive resources, and treat transient failures with retries and backoff. Hermes demonstrates bounded concurrency, chunking, and streaming I/O; the main improvements are connection reuse, fewer commits, retries in the LLM client, and parallelizing files and retries so the system scales with both file count and chunk count.
