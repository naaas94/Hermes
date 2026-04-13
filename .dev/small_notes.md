# More like thingies to look into rather than todos or path or next steps


# wal serialization concurrency

    Hermes uses SQLite with WAL. Concurrent extraction workers improve overlap of LLM calls; database writes still serialize at commit time. Under normal workloads this is usually negligible compared to model latency; it can matter with very high concurrency, very fast chunks, slow disks, or shared/network DB paths. Profile before changing architecture.

