# Would be nice's 


- Task 21: Add hermes list-schemas command
File: hermes/cli.py

What to add: A command that scans ~/.hermes/hermes_user/ and hermes/schemas/examples/ for Python files containing BaseModel subclasses, then prints them as valid --schema references.

Can reuse discover_schemas() from hermes/schemas/loader.py — but note that function is currently dead code (Task 10 deletes it). Decision: If Task 10 runs first, the agent for Task 21 needs to re-add discover_schemas or write the discovery inline. Coordinate accordingly — either keep discover_schemas (skip deleting it in Task 10) or rewrite it in Task 21.

Risk: Low. Discovery via importlib can raise if a user schema has syntax errors. Wrap in try/except.

---

- SQLite datetime deprecation (Python 3.12+)
Pytest warns because sqlite3’s default adapter for binding datetime objects is deprecated. It shows up on update_job_status in hermes/db.py when completed_at (a datetime) is passed in the UPDATE parameters—integration tests hit that path. Not a failing test; future-proof by converting datetimes to strings (e.g. .isoformat()) before execute, or registering explicit register_adapter/register_converter on the connection. Same pattern may apply anywhere else you bind datetime into SQLite.

---

- CI: “full stack” vs default pipeline (hermes test + real OCR)

**Flow (what stays out of default CI):** The main workflow installs `.[dev]` only—no `ocr` extra—then ruff, mypy, fixture generation, and pytest. Unit and integration tests mock the LLM (`create_llm_client`) and stub OCR (`_get_ocr_function`), so they exercise routing, chunking, DB, and CLI smoke without network LLM calls or ML stacks. Separately, `hermes test` (Typer command in `hermes/cli.py`) expects `test_excel_stress_synthetic.xlsx` and `test_pdf_stress_riscbac.pdf` from `generate_test_datasets.py` and runs the real pipeline with whatever provider is in config—benchmark-scale work (large Excel + multi-page PDF, many chunks/LLM calls). Real Surya/EasyOCR pulls torch-class dependencies and downloads models (e.g. Hugging Face); first run is slow and disk-heavy.

**Tradeoffs:** Putting all of that on every push means longer queues, larger runner disk use, flakiness from model downloads or rate limits, and optional API spend if `litellm` points at a cloud model. That fights the goal of fast, cheap PR feedback. Keeping heavy paths manual or off the default path is intentional, not an accidental gap.

**Paths that don’t run it on every push (pick one or combine):**

- **Branch / event filter:** Run an extra job only on `main` (or merge queue), not on every PR—still automatic, less fan-out.
- **Schedule + `workflow_dispatch`:** Nightly or weekly full job; humans trigger ad hoc runs when touching OCR or extraction.
- **Separate workflow file:** e.g. `ci-heavy.yml` so the default `ci.yml` stays the fast gate; heavy workflow is optional or required only for release branches.
- **Cache aggressively:** `actions/cache` for pip and Hugging Face hub dirs so repeat runs amortize downloads (does not fix cold-start time or torch install size on first run).
- **Self-hosted or larger runner:** If org policy allows—more disk/RAM for torch and models.
- **Smoke instead of benchmark:** A tiny one-page scanned PDF + mocked or minimal LLM in a dedicated job approximates OCR wiring without `hermes test` scale (still heavier than today, but bounded).
- **Document manual checklist:** Release or pre-release QA: install `.[ocr]`, generate datasets, run `hermes test` with intended provider.

Rationale summary: default CI proves correctness of the mocked, fast path; validating the full ML and benchmark path is valuable but belongs in a slower or manual tier so pushes stay cheap and predictable.

---

- | **§5** | `--quiet` | Audit mentioned verbosity; `--verbose` exists; **no `--quiet`** unless added later. |

---
