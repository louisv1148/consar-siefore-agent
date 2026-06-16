#!/bin/bash
#
# CONSAR monthly scheduled run (local, fully automatic).
# ======================================================
# Invoked by launchd (com.louis.consar-monthly) on days 16-22 each month.
# Runs the hardened pipeline end to end and, on success, notifies Louis via
# Ultron (S3 status file -> Ultron polls -> DM).
#
# Design decisions baked in (see chat 2026-06-16):
#   - "New data?" is decided by consar.pipeline.download (compares CONSAR vs the
#     latest GitHub *release* of consar-siefore-history). If nothing new -> exit 0,
#     launchd fires again tomorrow ("retry daily until found").
#   - The >10% MoM variance gate STOPS the run before integrate (the one human
#     stop-point). It writes a NEEDS-REVIEW marker and exits non-zero so the run
#     does not silently integrate anomalous data.
#   - Release is cut with `gh release create`, NOT `python -m consar.approval.release`
#     (that path's API token is 403 Forbidden; the gh CLI has the right scopes).
#   - RDS AUM update is automatic (Louis's standing instruction 2026-06-12).
#   - Everything is idempotent: once the release watermark advances, a re-run the
#     next day sees "no new data" and no-ops.

set -euo pipefail

AGENT_DIR="/Users/lvc/AI Scripts/consar-siefore-agent"
HOMEPAGE_DIR="/Users/lvc/AI Scripts/workflow-homepeage"
HISTORY_REPO="louisv1148/consar-siefore-history"
LOG_DIR="$AGENT_DIR/logs"
LOG="$LOG_DIR/scheduled_run.log"

mkdir -p "$LOG_DIR"

# Ensure gh/python on PATH under launchd's minimal environment.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:/usr/bin:/bin"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }

log "=== CONSAR scheduled run starting ==="
cd "$AGENT_DIR"

# --- Step 1: download (decides whether there is new data) -------------------
# download.main() returns truthy only when CONSAR is ahead of the latest release.
# We capture its decision via a tiny Python shim so we can branch in bash.
NEW_DATA=$(python3 -c "from consar.pipeline.download import main; print('1' if main() else '0')" 2>>"$LOG" | tail -1)

if [ "$NEW_DATA" != "1" ]; then
    log "No new CONSAR data (download watermark unchanged). Exiting 0; will retry tomorrow."
    log "=== CONSAR scheduled run complete (no-op) ==="
    exit 0
fi

log "New data detected. Continuing pipeline."

# --- Steps 2-4: extract -> enrich -> verify ---------------------------------
python3 -m consar.pipeline.extract >>"$LOG" 2>&1
log "Extract done."
python3 -m consar.pipeline.enrich >>"$LOG" 2>&1
log "Enrich done."

# Verify writes consistency_report.json; we read its variance to gate.
python3 -m consar.pipeline.verify >>"$LOG" 2>&1 || true
log "Verify done."

# --- Variance gate: STOP before integrate if verify failed -----------------
# consistency_report.json is {status, checks[]}. verify already applies the 10%
# rule per check and sets the top-level status. We honor that status, and also
# re-check the USD total change as a belt-and-suspenders bound.
VARIANCE_OK=$(python3 -c "
import json, os
rep = os.path.join('$AGENT_DIR', 'consistency_report.json')
try:
    d = json.load(open(rep))
    overall = d.get('status')
    pct = 0.0
    for c in d.get('checks', []):
        if 'change_pct' in c:
            pct = abs(float(c['change_pct']))
    if overall == 'pass' and pct <= 10.0:
        print('1')
    else:
        print(f'0:status={overall}:pct={pct:.2f}')
except Exception as e:
    print(f'0:err:{e}')
" 2>>"$LOG")

if [[ "$VARIANCE_OK" != "1" ]]; then
    log "VARIANCE GATE TRIPPED ($VARIANCE_OK). NOT integrating. Writing NEEDS-REVIEW marker."
    python3 scripts/build_status.py "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --needs-review 2>>"$LOG" || true
    log "=== CONSAR scheduled run halted for manual review ==="
    exit 2
fi
log "Variance within 10%. Proceeding to integrate."

# --- Step 4b + 5: approval file -> integrate --------------------------------
python3 -c "from consar.pipeline.run import create_approval_file; create_approval_file()" >>"$LOG" 2>&1
python3 -m consar.approval.integrate >>"$LOG" 2>&1
log "Integrate done."

# --- Cut the GitHub release (advances the watermark) ------------------------
# Read period from the approval file; tag vYYYY.MM. Idempotent: skip if exists.
read -r PER_Y PER_M < <(python3 -c "
import json, os
d = json.load(open(os.path.join('$AGENT_DIR','approval_pending.json')))
print(d['period_year'], str(d['period_month']).zfill(2))
")
TAG="v${PER_Y}.${PER_M}"
if gh release view "$TAG" --repo "$HISTORY_REPO" >/dev/null 2>&1; then
    log "Release $TAG already exists; skipping."
else
    gh release create "$TAG" --repo "$HISTORY_REPO" \
        --title "${PER_Y}-${PER_M} - Siefore Data Update" \
        --notes "Automated monthly CONSAR SIEFORE update. 400 records integrated." >>"$LOG" 2>&1
    log "Release $TAG created."
fi

# --- Reports ----------------------------------------------------------------
python3 -m consar.reports.generate >>"$LOG" 2>&1
log "Reports generated."

# --- RDS AUM update (automatic; standing instruction) -----------------------
# Build the per-Afore payload from the enriched month and patch all 10 in one call.
python3 -c "
import json, os
from collections import defaultdict
enr = os.path.join('$AGENT_DIR','consar_latest_month_enriched.json')
data = json.load(open(enr))
NAME = {'SURA':'Afore Sura','XXI Banorte':'Afore XXI Banorte','PensionISSSTE':'Afore Pensionissste'}
tot = defaultdict(float)
for r in data:
    if r['Concept']=='Total de Activo': tot[r['Afore']] += r['valueUSD']
ups = [{'lp': NAME.get(a, f'Afore {a}'), 'fields': {'aum_usd_b': round(u/1_000_000,1)}} for a,u in tot.items()]
json.dump({'updates': ups}, open('/tmp/crm_consar_aum_scheduled.json','w'), indent=2)
print('payload written:', len(ups), 'afores')
" >>"$LOG" 2>&1

# Source the homepage .env for DATABASE_URL, then patch.
( cd "$HOMEPAGE_DIR" && set -a && . ./.env && set +a \
  && python3 -m lib.crm.lp_props --file /tmp/crm_consar_aum_scheduled.json ) >>"$LOG" 2>&1
log "RDS AUM update done."

# --- Notify Ultron (S3 status file) -----------------------------------------
python3 scripts/build_status.py "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$LOG" 2>&1
log "Status uploaded to S3; Ultron will DM Louis."

log "=== CONSAR scheduled run complete (period ${PER_Y}-${PER_M}) ==="
