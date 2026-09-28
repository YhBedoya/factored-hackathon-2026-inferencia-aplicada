"""The append-only audit trail every guarded decision writes to.

See `docs/solution-docs/04-contracts.md` §6, D12, D13, D15. This module
carries no imports: `app.domains.conversation` reaches only `audit.schemas`
(the `Recorder` Protocol), and importing this package must never pull in
`audit.repository`'s database dependency along with it (`06` §2).
"""
