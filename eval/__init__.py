"""Eval package root (D5-B, B2/B3): scenario schema, the scripted HTTP
driver, prompts and test-set tooling live under `eval/`. This file stays
import-free -- `eval/scenarios/__init__.py` does too, on purpose, so
`freeze.check` (`make eval-freeze-check`, run by CI) stays stdlib-only (see
`docs/plans/d5-b-decline-explainer-test-sets.md` "Facts checked against the
repo").

`eval/` has no installed package name to collide with; `uv run --project
backend python -m eval.<module>` resolves it as a namespace-rooted package
from the repo root because `backend/pyproject.toml`'s `pythonpath` and this
package's presence put the repo root on `sys.path` (pytest's "prepend"
import mode does the same for `eval/tests`).
"""
