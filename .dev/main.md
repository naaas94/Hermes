

## To-dos
    - review pdf eval not passing hermes eval for page range
    - run tests and eval and bench 
    - go over retros
    - go over wbn and others to distill 

## Missing
    - need to leverage obs and eval more
        - usd cost / rss / and how it's being presented and benchmarked 


## Glossary 

    Below is a formal spec you can paste into a todo log or .dev note. It merges your original intent with the mechanics we discussed, keeps one global glossary.md as optional, and bakes in delta-only, dedup, cross-folder concepts, and light tooling, plus a Skill.md horizon.

Hermes engineering glossary — formal intent & operating spec
Original intent
Build a repeatable way to surface engineering concepts that appear in Hermes (patterns, tradeoffs, infrastructure behavior) so you can study them systematically. Output is glossary-like: short entries tied to what the code does and where, not generic lectures. Work is done incrementally (by folder, theme, or module), with only new material merged in each pass.

Design principles
Fixed output schema for every entry so notes stay scannable and comparable.
Delta-only updates: each agent pass adds only concepts not already captured under the dedup rules.
Dedup contract so the same idea does not multiply under different phrasing or slices.
Cross-folder concepts: one conceptual “home,” with pointers elsewhere as needed.
Artifact layout is flexible: a single file is one option, not a requirement until you choose it (e.g. multiple files by theme or slice is equally valid).
Light tooling: minimal process aids (sweep markers, optional index) — no heavy app unless you outgrow markdown.
Skill.md horizon: eventually encode this contract as a Cursor Agent Skill so runs stay consistent without re-pasting prompts.
Fixed output schema (per concept entry)
Each entry uses the same fields:

Field	Purpose
Canonical title
Short, stable phrase — primary dedup key.
Aliases (optional)
Other names/phrasings for the same idea.
What Hermes does
2–5 sentences, behavior-specific.
Where
Paths, symbols, optional line ranges after verification.
Why it matters here
Failure modes, constraints, or product tradeoffs in this codebase.
Study hooks
1–3 pointers for external reading (docs, papers, library notes).
Related
Links to internal docs (e.g. system-audit, decision logs) if useful.
Optional tags: e.g. core | deep-dive | nice-to-know — to prioritize reading.

Dedup contract
Primary key: Canonical title (normalized mentally: same idea → one title).
Secondary: Aliases — if a new phrasing matches an existing title or alias, do not add a second entry; extend the existing one (extra sentence, extra Where bullet).
Cross-artifact dedup: If you use multiple files (e.g. per theme), the agent must read all relevant glossary artifacts you designate for that run (or a small index listing known titles — see light tooling) before emitting deltas.
Uncertainty: If duplicate status is unclear, output a single “candidate merge” note under one title instead of two full entries.
When a concept spans folders
Single conceptual home: one canonical entry (one title) in the most representative slice or file.
Elsewhere: short “See also” or additional Where bullets for other paths — not duplicate full entries.
If the idea is truly cross-cutting (e.g. SQLite, worker pools), prefer a theme section or theme file (e.g. persistence, concurrency) and point modules to it.
Agent workflow (delta-only)
Inputs: (a) glossary artifact(s) and/or index of known canonical titles, (b) target scope (folder, files, or theme).
Extract candidate concepts from that scope only (code, comments, docstrings, high-signal names).
Filter: remove any candidate whose canonical title or alias already exists in the inputs.
Emit: only new entries using the fixed schema (append or insert into the agreed section/file).
Record sweep (light tooling): update “last swept” for that scope (see below).
Optional two-phase pass for noisy areas: (A) list candidate titles only, (B) fill schema for approved titles.

Artifact options (single file not required)
Option A — One file: sections by slice or theme; simplest for global search.
Option B — Multiple files: e.g. glossary-persistence.md, glossary-cli.md; requires a tiny index or cross-file read for dedup.
Option C — Hybrid: one index (glossary-index.md) listing canonical titles + file anchor; bodies live in slice files.
Choose one; the dedup contract applies regardless — only the read set before each delta changes.

Light tooling (minimal)
Sweep log — table or bullet list: scope, date, commit or branch (optional). Lets you see staleness without parsing git.
Optional title index — flat list of canonical titles (and aliases) for fast duplicate checks when using multiple files.
Front matter block in each glossary artifact: “How to update” — one paragraph: schema, delta rule, dedup, where sweep log lives.
No automation required initially; add scripts only if manual merge becomes painful.

Skill.md horizon
Goal: A Cursor Skill (e.g. hermes-glossary-mining/SKILL.md) that states: purpose, schema, dedup rules, delta-only workflow, cross-folder rule, which artifacts to read for a given command, and optional sweep-log update.
Trigger: “Glossary pass on hermes/…” or “Delta glossary for theme X.”
Benefit: Reproducible runs without re-copying the contract; aligns with your other orchestration/executor skills.
