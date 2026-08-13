"""Unit tests for runbook_lookup.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import runbook_lookup


def test_all_expected_runbooks_exist():
    available = runbook_lookup.list_available_issue_types()
    for expected in ["disk_full", "high_cpu", "network_latency", "service_down"]:
        assert expected in available


def test_get_runbook_content_returns_matching_file():
    content = runbook_lookup.get_runbook_content("high_cpu")
    assert content.startswith("# Runbook: High CPU Utilization")
    assert "## Escalation" in content


def test_issue_type_matching_is_normalized():
    exact = runbook_lookup.get_runbook_content("service_down")
    spaced = runbook_lookup.get_runbook_content("Service Down")
    hyphenated = runbook_lookup.get_runbook_content("service-down")
    assert exact == spaced == hyphenated


def test_unknown_issue_type_raises_with_available_list():
    with pytest.raises(FileNotFoundError) as exc_info:
        runbook_lookup.get_runbook_content("warp_core_breach")
    assert "high_cpu" in str(exc_info.value)


def test_empty_issue_type_raises():
    with pytest.raises(FileNotFoundError):
        runbook_lookup.get_runbook_content("")


def test_whitespace_only_issue_type_raises():
    with pytest.raises(FileNotFoundError):
        runbook_lookup.get_runbook_content("   ")


@pytest.mark.parametrize(
    "malicious_input",
    [
        "../README",
        "../../.env",
        "../../../../windows/win.ini",
        "..%2f..%2f.env",
        "high_cpu/../../../../windows/win.ini",
        "/etc/passwd",
    ],
)
def test_path_traversal_is_blocked(malicious_input):
    """Regression test: get_runbook_content must never read a file
    outside runbooks/, no matter what issue_type contains."""
    with pytest.raises(FileNotFoundError):
        runbook_lookup.get_runbook_content(malicious_input)
