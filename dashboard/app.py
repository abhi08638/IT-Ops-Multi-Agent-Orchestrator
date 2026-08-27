"""dashboard/app.py — one-page Streamlit dashboard for the IT Ops
orchestrator.

    streamlit run dashboard/app.py

Shows recent tickets processed, auto-remediated vs. escalated counts,
and the pending-approvals queue (the hard approval gate) with an
Approve button that resumes the paused LangGraph run for real — the
same resume_incident() path verified live against the real MCP server
and checkpointer in orchestrator/run_graph_demo.py.
"""

import asyncio
import html
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

import approvals
import incident_log
from graph import resume_incident
from mcp_client import mcp_tools_session

st.set_page_config(page_title="IT Ops Orchestrator", page_icon="🛠️", layout="wide")

approvals.init_db()
incident_log.init_db()

_DECISION_LABELS = {
    "auto_remediated": "Auto-remediated",
    "escalated": "Escalated",
    "pending_approval": "Pending Approval",
}

# Natural, past-tense phrasing for each known action code — matches the
# style of the mock executor's own log messages (see
# mcp_server/remediation_log.py), rather than a generic title-cased
# rendering of the action code.
_ACTION_PHRASES = {
    "restart_service": "Restarted service",
    "clear_disk_space": "Cleared disk space",
    "scale_out": "Scaled out",
}


def _humanize(value: str | None) -> str:
    """Turn a snake_case code into regular text, e.g. 'network_latency'
    -> 'Network Latency', 'high_cpu' -> 'High CPU'."""
    if not value:
        return "—"
    return value.replace("_", " ").title().replace("Cpu", "CPU")


def _action_taken(row: dict) -> str:
    """A specific, realistic description of what was actually executed
    -- e.g. 'Restarted service on vpn-auth-service' -- not just the
    decision code. Only auto_remediated rows have one: nothing was
    actually executed for escalated or still-pending rows."""
    if not row["action"]:
        return "—"
    phrase = _ACTION_PHRASES.get(row["action"], _humanize(row["action"]))
    return f"{phrase} on {row['target']}"


_TABLE_COLUMNS = ["Ticket", "Title", "Severity", "Issue Type", "Decision", "Action Taken", "Updated"]


def _recent_tickets_table_html(recent: list[dict]) -> str:
    """Hand-rolled HTML table (st.table gives no per-cell control) so the
    Decision cell can carry the escalation/approval reason as a native
    hover tooltip via the title attribute -- only rows with a reason
    (today, just escalated ones) get one."""
    header_cells = "".join(f"<th style='text-align:left; padding:4px 10px;'>{c}</th>" for c in _TABLE_COLUMNS)

    body_rows = []
    for row in recent:
        decision_label = html.escape(_DECISION_LABELS.get(row["decision"], _humanize(row["decision"])))
        reason = row.get("reason")
        if reason:
            decision_cell = (
                f"<span title='{html.escape(reason)}' "
                f"style='cursor: help; border-bottom: 1px dotted currentColor;'>{decision_label}</span>"
            )
        else:
            decision_cell = decision_label

        cells = [
            html.escape(row["ticket_id"]),
            html.escape(row["title"] or ""),
            html.escape(_humanize(row["severity"])),
            html.escape(_humanize(row["issue_type"])),
            decision_cell,
            html.escape(_action_taken(row)),
            html.escape(row["updated_at"]),
        ]
        body_rows.append(
            "<tr>" + "".join(f"<td style='padding:4px 10px;'>{c}</td>" for c in cells) + "</tr>"
        )

    return (
        "<table style='width:100%; border-collapse:collapse;'>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


def _approve(thread_id: str, ticket_id: str) -> None:
    """Resume a paused thread for real: spawns a fresh MCP session
    (a new subprocess) and reconnects to the same checkpoint file the
    paused run left behind — nothing about this run is held in
    Streamlit's memory between the pause and this click."""

    async def _run():
        async with mcp_tools_session() as tools:
            return await resume_incident(tools, thread_id, ticket_id, approved=True)

    return asyncio.run(_run())


st.title("🛠️ IT Ops Orchestrator")

# --- Stats -----------------------------------------------------------------
counts = incident_log.count_by_decision()
col1, col2, col3 = st.columns(3)
col1.metric("Auto-remediated", counts.get("auto_remediated", 0))
col2.metric("Escalated", counts.get("escalated", 0))
col3.metric("Pending approval", counts.get("pending_approval", 0))

st.divider()

# --- Pending approvals queue -------------------------------------------
st.subheader("Pending Approvals")
pending = approvals.list_pending()

if not pending:
    st.caption("No incidents currently awaiting approval.")
else:
    for row in pending:
        with st.container(border=True):
            left, right = st.columns([5, 1])
            with left:
                st.markdown(
                    f"**{row['ticket_id']}** — severity `{row['severity']}` · "
                    f"issue type `{row['issue_type']}`"
                )
                st.write(f"Proposed action: **{row['action']}** on `{row['target']}`")
                st.caption(row["reason"])
                st.caption(f"Paused since {row['created_at']}")
            with right:
                if st.button("Approve", key=f"approve-{row['thread_id']}", type="primary"):
                    with st.spinner("Resuming and executing…"):
                        try:
                            result = _approve(row["thread_id"], row["ticket_id"])
                        except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
                            st.error(f"Failed to resume {row['ticket_id']}: {exc}")
                        else:
                            st.success(f"{row['ticket_id']} approved -> {result.decision}")
                            st.rerun()

st.divider()

# --- Recent tickets ----------------------------------------------------
st.subheader("Recent Tickets")
recent = incident_log.list_recent(limit=20)

if not recent:
    st.caption("No tickets processed yet. Run orchestrator/run_graph_demo.py to generate some.")
else:
    # Hand-rolled HTML via st.markdown, not st.table/st.dataframe:
    # st.dataframe's canvas/WebGL grid was confirmed rendering an empty
    # container in earlier testing (correctly sized, nothing painted
    # inside), and st.table gives no way to attach a per-cell tooltip.
    # Plain HTML has neither problem.
    st.caption("Hover over a Decision to see the reason, where one was recorded.")
    st.markdown(_recent_tickets_table_html(recent), unsafe_allow_html=True)

if st.button("Refresh"):
    st.rerun()
