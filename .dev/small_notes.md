# More like thingies to look into rather than todos or path or next steps


## Experiment with chunk size 
    xslx chunk size currently is 180 so 154 chunks per test of 28k ish tokens 
        since we're using cloud we could play around chunk size and potentially token size 

        implemented 4/11 - max table rows 80


# wal serialization concurrency

    Hermes uses SQLite with WAL. Concurrent extraction workers improve overlap of LLM calls; database writes still serialize at commit time. Under normal workloads this is usually negligible compared to model latency; it can matter with very high concurrency, very fast chunks, slow disks, or shared/network DB paths. Profile before changing architecture.

