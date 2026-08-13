"""Runbook lookup for the get_runbook MCP tool.

Runbooks are plain markdown files in runbooks/, one per issue type. The
issue_type argument is normalized (lowercased, spaces/hyphens ->
underscores) before matching a filename, so "High CPU", "high-cpu", and
"high_cpu" all resolve to runbooks/high_cpu.md.
"""

import re
from pathlib import Path

RUNBOOKS_DIR = Path(__file__).resolve().parent / "runbooks"


def _normalize(issue_type: str) -> str:
    """Slugify issue_type into a safe filename stem.

    Only [a-z0-9_] survives — this is an allowlist, not a blocklist, so
    path separators, '..', percent-encoding, etc. all get stripped rather
    than specifically detected. That's what keeps get_runbook_content()
    from being a path-traversal read of arbitrary files on disk.
    """
    slug = issue_type.strip().lower()
    slug = re.sub(r"[\s-]+", "_", slug)
    return re.sub(r"[^a-z0-9_]", "", slug)


def list_available_issue_types() -> list[str]:
    """Return the issue types with a runbook on disk, e.g. ['disk_full', ...]."""
    return sorted(p.stem for p in RUNBOOKS_DIR.glob("*.md"))


def get_runbook_content(issue_type: str) -> str:
    """Return the markdown contents of the runbook matching issue_type.

    Raises FileNotFoundError (listing the known issue types) if nothing
    matches, rather than fabricating a runbook that doesn't exist.
    """
    runbooks_dir = RUNBOOKS_DIR.resolve()
    path = (runbooks_dir / f"{_normalize(issue_type)}.md").resolve()

    # Belt-and-braces: even though _normalize() already allowlists to
    # [a-z0-9_], explicitly refuse to serve anything that resolves outside
    # runbooks/ rather than trusting the slug alone.
    if not path.is_relative_to(runbooks_dir) or not path.exists():
        available = ", ".join(list_available_issue_types())
        raise FileNotFoundError(
            f"No runbook found for issue_type={issue_type!r}. "
            f"Available issue types: {available}"
        )
    return path.read_text(encoding="utf-8")
