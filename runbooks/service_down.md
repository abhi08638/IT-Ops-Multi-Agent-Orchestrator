# Runbook: Service Down

## Symptoms
- Health checks failing across all or most instances
- 5xx errors or connection-refused responses for clients
- Service not responding to requests at all

## Diagnosis
1. Confirm the outage: check the health check endpoint and recent deploy
   history.
2. Check process status on the affected host(s) — is the process running
   at all?
3. Check for recent config or dependency changes (database, downstream
   API, credentials).
4. Review logs for crash loops or startup failures.

## Remediation
- If the process crashed, restart it.
- If a bad deploy is the cause, roll back to the last known-good version.
- If a dependency (database, cache, downstream service) is down, escalate
  to the owning team instead of repeatedly restarting.

## Escalation
Always escalate a full outage on a critical system immediately — don't
wait for auto-remediation to resolve it. Cap restart attempts (e.g. 2
tries) before escalating.
