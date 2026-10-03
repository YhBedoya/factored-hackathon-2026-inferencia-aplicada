"""Scenario file tree: `dev/`, `_staging/heldout/` (drafts, D11) and, once a
human runs `make eval-freeze`, `heldout/` + `heldout.lock`.

Deliberately imports nothing -- not even `schema` -- so that `freeze.check`
(CI's `make eval-freeze-check`) can import this package and stay
stdlib-only, per the card's D12/D11 boundary: no agent-controlled code path
reaches network or LLM code on the path that verifies the held-out hash.
"""
