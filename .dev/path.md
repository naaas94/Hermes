# Let's organize next steps before release


## Let's fix what's already here

Go over [system-audit.md] with agents and knock lists of TODOs 
    - update 4_10; knocked 20 tasks off, have some more to do and will be done. 
    - update 4_11: Knocked remaining todos, only some minor or yatch problems remain. 

## Eval as differentiator

Go over [evaluation-and-health-metrics-roadmap.md]
    - instantiate roboust eval
    - don't undersell or lean on scalability and memory safe features - The selling points


## Readme update
    Reframe the opening line around what Hermes is (schema-driven document → validated JSON extraction) and how it runs (cloud or local LLMs via config), then highlight differentiators you can stand behind now or soon: memory-safe / streaming processing, observability (tokens, latency, validation, DLQ/replay), concurrency for cloud. Move local-first / offline / privacy from headline to a clear optional path (Ollama, no third-party API) so compliance-minded readers still see it in a deliberate scan.

    Tradeoffs: Leading with cloud-friendlier language may understate air-gapped and strict data-residency buyers unless you repeat offline/privacy once prominently; overcorrecting toward cloud can sound like “vendor SaaS” when Hermes is a CLI + local storage. Cost/latency anecdotes ($0.12, ~700s) are workload- and model-dependent — use as illustration, not a promise. Memory-safe is strong only if you avoid vague claims or plan to back it with numbers per your roadmap. Order of features signals default audience: developers optimizing throughput and ops vs those optimizing data sovereignty.