# Rollback & recovery

Production: Fly.io app `gradient-jobs`, region `bom`, one machine (API + scheduler), SQLite on volume `gradient_data` at `/data`.

## Decision rule
Site down, or `/api/health` failing for 5 minutes, or a sweep visibly corrupting listings: **roll back first, debug after.**

## Bad deploy → previous release
```bash
fly releases                       # find the last good version (vN) and its image
fly deploy --image <image-of-vN>   # redeploy that exact image; no rebuild
fly status && curl -s https://gradient-jobs.fly.dev/api/health
```
Last-known-good release: _record after first healthy deploy_ (`fly releases`, top row).

## Kill switches (no code change)
| Problem | Command |
|---|---|
| LinkedIn objects / throttles us | `fly secrets set GRADIENT_ENABLE_LINKEDIN=false` (restarts the machine) |
| Sweeps overloading the machine | `fly secrets set GRADIENT_SOURCES_IN_FLIGHT=12`, or scale up: `fly scale memory 2048` |
| Stop scraping entirely, keep the site up | `fly secrets set GRADIENT_EMBEDDED_WORKER=false` |

## Bad sweep (mass false closures, junk listings)
- Closures are evidence-based and reversible: a job that reappears in its source reopens on the next sweep.
- Classifier/trust bug: revert the change, bump `CLASSIFIER_VERSION` in `backend/gradient/ingest/pipeline.py`, redeploy. To re-apply trust rules without scraping: `fly ssh console -C "python -m gradient.cli rescore"`.
- Data damaged → restore a snapshot (below).

## Database backups
- **App snapshots:** daily at 03:30 IST to `/data/backups/`, 14 kept (`gradient/backup.py`). Manual: `fly ssh console -C "python -m gradient.cli backup"`.
- **Fly volume snapshots:** Fly snapshots the volume daily (kept 5 days by default). Check them with `fly volumes list`, then `fly volumes snapshots list <vol-id>`. These survive loss of the volume itself, which the in-volume snapshots don't.
- **Off-site copy:** `fly ssh sftp get /data/backups/<file>.db` to keep one locally.
- **Restore an app snapshot:**
  `fly ssh console -C "python -m gradient.cli restore /data/backups/<file>.db"`, then `fly machine restart`.
- **Restore a volume snapshot:** `fly volumes create gradient_data --snapshot-id <id> --region bom`, then point the machine at it (see Fly docs, "Restore from snapshot").
- Restore tested locally 2026-10-22: snapshot restored with integrity_check `ok` (2,888 jobs, 2,074 boards). Repeat once in production.

## Watch after any deploy
`fly logs` (sweep lines: `gradient.pipeline: run N done`), `/status` page (last sweep, failed sources), `fly status` (machine health checks).

## Telling users
Site-wide issue: post on the `/status` page's banner (future) or your social channels: "Gradient listings are paused while we fix an issue; existing links still go to employers' official pages."
