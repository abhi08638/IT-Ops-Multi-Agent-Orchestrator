# Runbook: Disk Full / High Disk Usage

## Symptoms
- Disk utilization alert above 90%
- Write failures or "No space left on device" errors in logs
- Database or log-writing services failing unexpectedly

## Diagnosis
1. Identify what's consuming space (`du -sh /* | sort -rh | head`).
2. Check for oversized or unrotated log files.
3. Check for old backups, core dumps, or temp files that were never
   cleaned up.
4. Confirm whether usage growth is a one-time spike or a steady trend
   (a leak).

## Remediation
- Clear or rotate oversized logs (compress/archive rather than delete if
  retention matters).
- Remove stale temp files, old core dumps, or superseded backups.
- If space isn't recoverable quickly, expand the volume.

## Escalation
Escalate if the disk is on a production database or backup-service host,
or if usage keeps climbing after cleanup — that indicates a leak rather
than accumulated cruft.
