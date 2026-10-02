"""Interaction analytics: one stored row of metrics per finished interaction.

See `docs/specs/interaction-analytics-pipeline.md` (ADR-033). The domain reads
`app`, `audit` and `bank` with its own SQL (the `audit/repository.py`
precedent) and writes only the `analytics` schema. It imports no
`app.domains.conversation` module: the per-intent segments it needs arrive as
data in the `reply_sent` audit payload (D12).
"""
