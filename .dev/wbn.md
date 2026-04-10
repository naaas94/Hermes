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

