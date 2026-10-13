# Resume interrupted runs on the owning node

The first agent-capable version preserves interrupted work on its executing Local Node and waits for that node to return, then resumes from durable progress rather than automatically transferring the run to another device. This avoids prematurely requiring encrypted runtime-state replication and cross-device execution ownership while retaining offline continuity; coordinator-visible state remains policy-limited. Checkpoint and unknown-result recovery still need implementation, and resumption must not blindly repeat external side effects.
