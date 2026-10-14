# Back up local state with user-held keys

> Updated scope, 2026-10-14: local encrypted state backup and restore were validated, but the user deferred independent backup copies and recovery-key preparation because source data already has user-managed cloud backups. These are outside current PA0 acceptance; no periodic cloud-state backup or key export is enabled. Existing local archives and credentials remain. See [final acceptance](../pa0-acceptance.md).

Each local node will periodically produce encrypted backups of its SQLite state, memory ledger, and configuration to user-controlled cloud storage or offline media. The VPS will never receive the decryption key or act as the plaintext backup authority, preserving recovery of task and audit state without changing the personal-data boundary.
