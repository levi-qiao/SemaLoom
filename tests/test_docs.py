from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
PUBLIC_DOCS = (
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "quickstart.md",
    ROOT / "docs" / "capabilities.md",
)
PRIVATE_QUICKSTART_NEEDLES = (
    "remote-dev",
    "semaloom_samples",
    "semaloom_sample_meta",
    "tipdevrds",
    "OPENAI_API_KEY",
    "ANTHROPIC",
)
OVERCLAIM_NEEDLES = (
    "production identity adapter is implemented",
    "composite identity works",
    "published a signed SBOM",
)


def test_relative_markdown_links_resolve() -> None:
    documents = [
        *ROOT.glob("*.md"),
        *(ROOT / "docs").rglob("*.md"),
        *(ROOT / "semantic-spec").rglob("*.md"),
    ]
    missing: list[str] = []
    for document in documents:
        for raw_target in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>").split("#", maxsplit=1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")

    assert not missing, "broken relative Markdown links:\n" + "\n".join(sorted(missing))


def test_public_quickstart_is_synthetic_and_unpaid() -> None:
    text = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
    for needle in PRIVATE_QUICKSTART_NEEDLES:
        assert needle not in text, needle
    assert "No model key" in text
    assert "110.1000" in text
    assert "tax.reportedIncome" in text
    assert "sourceActivities" in text
    assert "incomeReconciles" in text
    assert "UNKNOWN" in text
    assert "actions/plan" in text
    assert "VERIFIED" in text
    assert "POLICY_PERIOD_SPLIT_REQUIRED" in text
    assert "postgresql@16" in text
    assert "local-dev" in text


def test_public_docs_do_not_overclaim_unshipped_gates() -> None:
    for document in PUBLIC_DOCS:
        text = document.read_text(encoding="utf-8")
        for needle in OVERCLAIM_NEEDLES:
            assert needle not in text, f"{document.name}: {needle}"
        if document.name in {"README.md", "quickstart.md", "capabilities.md"}:
            assert "remote-dev" not in text
            assert "semaloom_samples" not in text
            assert "tipdevrds" not in text


def test_capabilities_state_current_limits() -> None:
    text = (ROOT / "docs" / "capabilities.md").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "static name list" in lowered
    assert "mcp sdk transport" in lowered
    assert "first" in lowered and "key" in lowered
    assert "boolean" in lowered
    assert "draftstore" in lowered
    assert "rule editor" in lowered
    assert "local-dev" in lowered
    assert "signed sbom" in lowered
