# Share the MiMo key across the first two nodes

> Updated scope, 2026-10-14: ROG is removed from the active deployment. When PA1 is authorized, configure the provider credential only in Mac's Keychain; do not provision a ROG copy. The shared-key choice below applies only if the user explicitly restores a second inference node. No model credentials or calls are enabled by this update.

Mac and ROG will use the same MiMo API key for PA1, with each copy stored only in that node's system credential store. This reduces initial account setup, but a compromise or rotation requires replacing the key on both nodes; future per-node keys remain an available hardening change.
