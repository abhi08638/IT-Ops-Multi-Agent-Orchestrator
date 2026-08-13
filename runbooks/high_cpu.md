# Runbook: High CPU Utilization

## Symptoms
- Sustained CPU usage above 90% for more than 5 minutes
- Increased response latency or request timeouts
- Alerting fired from infrastructure monitoring

## Diagnosis
1. Identify the top CPU-consuming process (`top` / `ps aux --sort=-%cpu`).
2. Check for a recent deploy or config change correlated with the spike.
3. Determine whether traffic volume has genuinely increased (legitimate
   load) vs. a runaway process or infinite loop.
4. Check for stuck cron jobs or batch processes running outside their
   normal window.

## Remediation
- If a single runaway process is identified and it's safe to restart,
  restart the affected service.
- If load is legitimate, scale out (add nodes) rather than killing the
  process.
- If caused by a recent deploy, consider rolling back.

## Escalation
Escalate to a human if CPU remains above 90% for more than 15 minutes
after remediation, or if the affected system is customer-facing and
severity is critical.
