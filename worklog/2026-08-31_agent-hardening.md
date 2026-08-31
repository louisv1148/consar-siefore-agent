# Agent hardening: venv rebuild + stability pass (Louis-requested 2026-08-31, routed from hq sweep)
STATUS: ready-to-build

## Why
This repo's venv was copied from the retired `~/AI Scripts/2025_10 Consar Siefore Update Agent` — `venv/bin/runxlrd.py` still carries the shebang `#!/Users/lvc/AI Scripts/2025_10 Consar Siefore Update Agent/venv/bin/python3.13`, and other copied-venv paths may be equally stale. Louis: "refactor the siefore update agent so this is taken care of at the source. I want the working workflow optimized for stability, repeatability and accuracy. this situation seems like a weak link."

## Scope
- Rebuild the venv in place from a pinned `requirements.txt` (generate one from the current venv first if none exists) so no path points outside this repo.
- Audit for other absolute-path weak links (scripts, configs) — the launchd job `com.louis.consar-monthly` (days 16–22, 10:00) runs `scripts/scheduled_run.sh`; nothing may break for the ~Sept 16–22 window.
- Sanity-run the pipeline after rebuild (dry-run/no-op path — the script no-ops when CONSAR has no new data).
- After it survives a clean scheduled cycle: tell hq — the old `2025_10 Consar Siefore Update Agent` husk then archives (gate in `~/hq/PROJECTS.md` Paused).

## Timing
Do this OUTSIDE the launchd window (before Sept 16 or after Sept 22) so a mid-rebuild venv never meets a scheduled run.

## Resume
Open this repo's window, read this file. Note: dirty JSON in this repo is launchd run output, not abandoned work — don't "clean" it.

## Note (2026-08-31, hq session)
Local uncommitted launchd JSON output conflicted with newer GitHub-Actions data on the remote; working tree now matches origin/master (`8d8edbc`). The old local output is preserved in `stash@{0}` ("hq-sweep: launchd run output preserved during rebase") — inspect or drop it during the hardening pass. Two older WIP stashes also exist. Untracked `consar_status_latest.json` left in place.
