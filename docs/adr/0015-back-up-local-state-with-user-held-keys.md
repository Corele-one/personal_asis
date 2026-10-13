# Back up local state with user-held keys

Each local node will periodically produce encrypted backups of its SQLite state, memory ledger, and configuration to user-controlled cloud storage or offline media. The VPS will never receive the decryption key or act as the plaintext backup authority, preserving recovery of task and audit state without changing the personal-data boundary.
