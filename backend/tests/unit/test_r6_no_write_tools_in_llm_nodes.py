"""R6 (LLM nodes have no write tools) contract test.

See `docs/specs/d2-k-write-contracts.md` Decision D6 and §"Test list". A
source scan of every module under `conversation/nodes/` and
`conversation/flows/`: a module that imports `app.core.llm` must not
reference a write tool, by name or by import.
"""

import ast
from pathlib import Path

_FORBIDDEN_NAMES = (
    "bank_write_tools",
    "ConfirmedWriteTools",
    "BankWriteTools",
    "handoff_tools",
    "HandoffTools",
)
_FORBIDDEN_MODULES = (
    "app.domains.conversation.tools.write",
    "app.domains.conversation.tools.executor",
    "app.domains.conversation.tools.handoff",
)
_FORBIDDEN_ATTRS = ("write", "executor")


def _imports_llm(tree: ast.Module) -> bool:
    """True if `tree` imports the LLM package, in any of its import forms."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "app.core.llm" or alias.name.startswith("app.core.llm.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "app.core.llm" or module.startswith("app.core.llm."):
                return True
            if module == "app.core" and any(alias.name == "llm" for alias in node.names):
                return True
    return False


def _write_tool_references(source: str, tree: ast.Module) -> list[str]:
    """Offending write-tool references in `source`/`tree`, empty if none (R6)."""
    offenses = [name for name in _FORBIDDEN_NAMES if name in source]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenses.extend(alias.name for alias in node.names if alias.name in _FORBIDDEN_MODULES)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in _FORBIDDEN_MODULES:
                offenses.append(module)
            elif module == "app.domains.conversation.tools":
                offenses.extend(
                    alias.name for alias in node.names if alias.name in _FORBIDDEN_ATTRS
                )
    return offenses


def scan_llm_modules(root: Path) -> dict[Path, list[str]]:
    """Map each LLM-importing module under `root/nodes` and `root/flows` to its
    write-tool offenses (empty list if clean)."""
    found: dict[Path, list[str]] = {}
    for subdir in ("nodes", "flows"):
        for path in sorted((root / subdir).glob("*.py")):
            source = path.read_text()
            tree = ast.parse(source, filename=str(path))
            if _imports_llm(tree):
                found[path] = _write_tool_references(source, tree)
    return found


def test_llm_nodes_cannot_reach_write_tools() -> None:
    conversation_root = Path(__file__).resolve().parents[2] / "app" / "domains" / "conversation"
    scanned_llm_modules = scan_llm_modules(conversation_root)
    for path, offenses in scanned_llm_modules.items():
        assert not offenses, f"{path} imports app.core.llm but references write tool(s): {offenses}"

    assert scanned_llm_modules, "expected at least one nodes/flows module to import app.core.llm"
    # The handoff summary is an LLM node: it must be inside the scan, not skipped.
    assert any(path.name == "handoff_summary.py" for path in scanned_llm_modules)

    # Prove the scan isn't vacuous: it must flag a synthetic violation.
    snippet = "from app.core.llm import LLMClient\nx = config['configurable']['bank_write_tools']"
    snippet_tree = ast.parse(snippet)
    assert _imports_llm(snippet_tree)
    assert _write_tool_references(snippet, snippet_tree)

    for bad in (
        "from app.domains.conversation.tools.handoff import HandoffTools",
        "x = config['configurable']['handoff_tools']",
    ):
        bad_source = f"from app.core.llm import LLMClient\n{bad}"
        assert _write_tool_references(bad_source, ast.parse(bad_source))


def test_scan_flags_added_write_tool(tmp_path: Path) -> None:
    """D15a: a write-tool reference added to an LLM module is reported; a
    sibling module without the LLM import is not scanned into the result."""
    (tmp_path / "nodes").mkdir()
    (tmp_path / "flows").mkdir()
    evil = tmp_path / "nodes" / "evil.py"
    evil.write_text(
        "from app.core.llm import LLMClient\nx = config['configurable']['bank_write_tools']\n"
    )
    (tmp_path / "nodes" / "plain.py").write_text("x = config['configurable']['bank_write_tools']\n")

    found = scan_llm_modules(tmp_path)

    assert "bank_write_tools" in found[evil]
    assert list(found) == [evil]
