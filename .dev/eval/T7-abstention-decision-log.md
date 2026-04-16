# T7 — Abstention / false-positive remediation — decision log

## Chosen approach

- **Four-layer fix** (prompt + validator coercion + validator all-null filter + example schema anchor) so negative eval chunks score **`correct_abstention`** when the model should output **`[]`**, without changing eval scorer semantics.
- **Prompts** ([`hermes/extraction/prompts.py`](../../hermes/extraction/prompts.py)): add explicit rules to return **`[]`** when no record matches the schema and to avoid placeholder / null-only / explanatory wrapper objects. Bumps **`get_current_prompt_version()`** (16-char SHA of system + user templates).
- **Validator** ([`hermes/extraction/validator.py`](../../hermes/extraction/validator.py)):
  - **`parse_json_array`**: after unwrapping known wrapper keys (`items`, `records`, …), treat **`{}`** and dicts whose values are all **`None`** as **`[]`** instead of **`[dict]`**.
  - **`validate_with_repair`**: after **`validate_records`**, remove validated models whose **`model_dump`** is all **`None`** (defense against all-optional schemas).
- **Example schema** ([`hermes/schemas/examples/vehicle_fleet.py`](../../hermes/schemas/examples/vehicle_fleet.py)): require **`numero_serie`** (VIN) as the semantic anchor; other fields remain optional for partial rows.
- **Tests**: abstention phrases in prompts; parse behavior for **`{}`** / all-null dict; all-null row drop in repair loop; **`VehicleRecord`** JSON Schema **`required`** includes **`numero_serie`**; job-dedup mock LLM output updated to minimal valid **`VehicleRecord`**.
- **CLI**: rename verbose eval loop variable from **`fd`** to **`field_diff`** to avoid shadowing **`fixture_dir`** alias **`fd`** (mypy).

## Alternatives rejected

- **Prompt-only**: improves models that follow instructions but does not stop schema-trivial hallucinations or **`{}` → `[{}]`** coercion; rejected as sole fix.
- **Remove single-object coercion entirely**: would break common “one JSON object instead of array” LLM outputs; kept coercion for non-empty dicts.
- **Require both `marca` and `numero_serie`**: stricter but easier to drop legitimate rows when marca is missing in text; **`numero_serie` alone** is enough for the fleet slip use case.
- **Plumb negative / abstention hints from eval manifests into runtime extraction**: eval-only labels should not leak into production pipeline; out of scope for this remediation.

## Assumptions (load-bearing)

- **`_drop_all_null_validated`** is safe for bundled examples (`VehicleRecord` has a required field; **`GenericRow`** has required **`row_data`**). User schemas that are entirely optional and rely on “all null means present row” could be over-filtered—documented in CHANGELOG.
- **Job dedup** does not include prompt version (per existing product decision); changing prompts alone can still reuse a prior **completed** job until **`--force`** or other dedup inputs differ.
- **Live `hermes eval -v`** against real LLMs requires **`OPENAI_API_KEY`** (or configured provider); CI uses mocked LLM + golden replay (**`tests/test_eval_regression.py`**).

## Items deferred

- **Repair prompt** (`REPAIR_PROMPT_TEMPLATE`) does not yet repeat the abstention rule; add if repair loops still emit spurious rows.
- **README** section on abstention / schema anchors for custom schemas (optional doc follow-up).
