# Bind confirmation to the exact action

> Updated scope, 2026-10-14: [ADR 0033](0033-use-standing-personal-data-and-maintenance-authorizations.md) records explicit standing permission for existing-project maintenance and owner replies/notifications. Operations outside those scopes still require exact confirmation; source originals remain read-only.

Each external write requires a confirmation scope bound to its precise target, content, and key parameters for a limited time. A changed action requires a new confirmation, preventing a prior approval for one calendar event, email, or submission from silently authorizing another.
