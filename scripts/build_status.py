#!/usr/bin/env python3
"""
Build + upload the CONSAR run-status file that Ultron polls to notify Louis.

Called at the end of scripts/scheduled_run.sh after a successful integrate +
RDS AUM update. Aggregates the enriched month into per-Afore USD-billion AUMs,
writes a compact status JSON, and uploads it to the mattermost-dbbot S3 bucket.

Idempotent: re-running for the same period overwrites with identical content.
Exits non-zero (and prints) on any failure so the wrapper can log it; a failed
upload must NOT mask a successful data run.
"""

import json
import os
import sys
from collections import defaultdict

# bucket + key the Ultron bot reads (same bucket it pulls bot.py / packs from)
S3_BUCKET = os.environ.get("CONSAR_STATUS_BUCKET", "mattermost-dbbot-018585551357")
S3_KEY = os.environ.get("CONSAR_STATUS_KEY", "consar-status.json")

ENRICHED = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "consar_latest_month_enriched.json",
)


def build_status(generated_at: str) -> dict:
    """Aggregate the enriched month into a notification-ready status dict.

    generated_at is passed in (not computed) so the wrapper controls the
    timestamp and the run stays deterministic/testable.
    """
    with open(ENRICHED, "r", encoding="utf-8") as f:
        data = json.load(f)

    totals = defaultdict(float)
    for r in data:
        if r["Concept"] == "Total de Activo":
            totals[r["Afore"]] += r["valueUSD"]

    afores = {a: round(usd / 1_000_000, 1) for a, usd in sorted(totals.items())}
    total_b = round(sum(totals.values()) / 1_000_000, 1)

    period_year = data[0]["PeriodYear"]
    period_month = str(data[0]["PeriodMonth"]).zfill(2)
    fx = next((r.get("FX_EOM") for r in data if r.get("FX_EOM")), None)

    return {
        "schema": "consar.status.v1",
        "period": f"{period_year}-{period_month}",
        "generated_at": generated_at,
        "records": len(data),
        "fx_eom": fx,
        "total_aum_usd_b": total_b,
        "aum_by_afore_usd_b": afores,
        "crm_updated": True,
    }


def build_needs_review(generated_at: str) -> dict:
    """Status written when the variance gate trips: data was downloaded but NOT
    integrated. Ultron DMs Louis to review manually rather than reporting success.
    Period/variance read from consistency_report if available, best-effort."""
    period = "unknown"
    pct = None
    try:
        with open(ENRICHED, "r", encoding="utf-8") as f:
            data = json.load(f)
        period = f"{data[0]['PeriodYear']}-{str(data[0]['PeriodMonth']).zfill(2)}"
    except Exception:
        pass
    try:
        rep = os.path.join(os.path.dirname(ENRICHED), "consistency_report.json")
        d = json.load(open(rep))
        for c in d.get("checks", []):
            if "change_pct" in c:
                pct = round(float(c["change_pct"]), 2)
    except Exception:
        pass
    return {
        "schema": "consar.status.v1",
        "period": period,
        "generated_at": generated_at,
        "needs_review": True,
        "reason": "MoM variance gate tripped; data downloaded but NOT integrated.",
        "variance_pct": pct,
        "crm_updated": False,
    }


def main():
    # generated_at comes from argv[1] (wrapper passes `date -u`); Date.now is
    # deliberately not used here so the run is reproducible.
    generated_at = sys.argv[1] if len(sys.argv) > 1 else ""
    if "--needs-review" in sys.argv[2:]:
        status = build_needs_review(generated_at)
    else:
        status = build_status(generated_at)

    # Write a local copy for debugging / the wrapper's log.
    local = os.path.join(os.path.dirname(ENRICHED), "consar_status_latest.json")
    with open(local, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)

    import boto3

    boto3.client("s3").put_object(
        Bucket=S3_BUCKET,
        Key=S3_KEY,
        Body=json.dumps(status, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    print(f"✅ Uploaded status for {status['period']} to s3://{S3_BUCKET}/{S3_KEY}")
    print(f"   total_aum_usd_b={status['total_aum_usd_b']}  records={status['records']}")


if __name__ == "__main__":
    main()
