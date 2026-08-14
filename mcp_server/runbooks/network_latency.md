# Runbook: Elevated Network Latency

## Symptoms
- Increased request latency without a corresponding CPU/memory spike
- Intermittent timeouts between services
- Users report slowness rather than outright errors

## Diagnosis
1. Check whether latency is isolated to one region/link or system-wide.
2. Run basic connectivity checks (ping, traceroute) between affected
   hosts.
3. Check for recent network, firewall, or routing changes.
4. Correlate with traffic volume — is this congestion from legitimate
   load?

## Remediation
- If congestion from legitimate load, scale out or shift traffic away
  from the affected path.
- If caused by a recent network change, roll it back.
- If a specific link or provider is degraded, fail over to a backup path
  if one is available.

## Escalation
Escalate to network/infra on-call if latency persists more than 30
minutes or affects a critical customer-facing path — root cause is often
outside application code.
