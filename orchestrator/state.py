"""orchestrator/state.py — shared state passed between agent nodes."""

from dataclasses import dataclass, field


@dataclass
class IncidentState:
    """Accumulates as it flows through Intake -> Triage -> Remediation.

    `log` is a running, human-readable trail of what each agent did and
    why, consistent with the project's "every decision gets logged"
    design intent — it's meant to be readable end to end, not just a
    debug aid.
    """

    ticket_id: str
    ticket: dict | None = None
    issue_type: str | None = None
    severity: str | None = None
    runbook: str | None = None
    route: str | None = None  # "remediate" | "escalate" | None — the supervisor's routing choice
    decision: str | None = None  # "auto_remediated" | "escalated" | None — the final outcome
    remediation_result: dict | None = None
    escalation_reason: str | None = None
    log: list[str] = field(default_factory=list)
