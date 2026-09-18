"""System portfolio composition for the monthly PDF report.

Source: the cartera history file written by `consar.pipeline.cartera --update`
(CONSAR SISET md=18, % of net assets, monthly since Ene 2019). This module only
READS that file — it never fetches. If the file is missing or its latest period
does not match the report period, the caller gets `None` plus a reason and skips
the section rather than failing the whole report.

The nine top-level categories partition the portfolio and must sum to 100%; the
table prints the TOTAL so a renamed or dropped category is visible on the page
instead of silently shrinking the total (that failure cost 11.34% of the
portfolio until 2026-09-17 — see GROUPS in consar/pipeline/cartera.py).
"""

import json
import math
import os

from consar.pipeline.cartera import (
    CARTERA_TOP_LEVEL,
    GROUPS_TOTAL_TOLERANCE,
    HISTORY_FILE,
)

# Shorter labels for the PDF column; the history keys stay as published.
DISPLAY_NAMES = {
    "Renta Variable Nacional": "Equity - Domestic",
    "Renta Variable Internacional": "Equity - International",
    "Mercancías": "Commodities",
    "Deuda Nacional - Corporativa y Bancaria": "Debt - Domestic Corporate & Bank",
    "Deuda Gubernamental": "Debt - Government",
    "Deuda Internacional": "Debt - International",
    "Estructurados": "Structured (CKDs / CERPIs)",
    "FIBRAS": "FIBRAS (listed real estate)",
    "Otros Activos": "Other Assets",
}


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _prior_period(period):
    year, month = int(period[:4]), int(period[5:])
    return f"{year - 1:04d}-12" if month == 1 else f"{year:04d}-{month - 1:02d}"


def load_composition(report_period=None):
    """Return (data, reason).

    data is None when the section cannot be rendered; `reason` then says why.
    On success data is a dict with `period`, `rows` and `total`.
    """
    if not os.path.exists(HISTORY_FILE):
        return None, f"cartera history not found at {HISTORY_FILE}"
    try:
        with open(HISTORY_FILE, encoding="utf-8") as fh:
            doc = json.load(fh)
        categories = doc["categories"]
    except (ValueError, KeyError, OSError) as exc:
        return None, f"cartera history unreadable: {exc}"

    periods = sorted({p for series in categories.values() for p in series})
    if not periods:
        return None, "cartera history has no periods"
    latest = periods[-1]
    if report_period and report_period != latest:
        return None, f"cartera history is at {latest}, report is {report_period}"

    prev = _prior_period(latest)
    yoy = f"{int(latest[:4]) - 1}{latest[4:]}"

    rows, total = [], 0.0
    for name in CARTERA_TOP_LEVEL:
        series = categories.get(name, {})
        pct = _clean(series.get(latest))
        if pct is None:
            continue
        total += pct
        before = _clean(series.get(prev))
        year_ago = _clean(series.get(yoy))
        rows.append(
            {
                "name": name,
                "label": DISPLAY_NAMES.get(name, name),
                "pct": pct,
                "mom": None if before is None else pct - before,
                "yoy": None if year_ago is None else pct - year_ago,
            }
        )

    if not rows:
        return None, f"no top-level categories carry a value for {latest}"

    rows.sort(key=lambda r: r["pct"], reverse=True)
    return {"period": latest, "rows": rows, "total": total, "updated_at": doc.get("updated_at")}, None


def build_table(data, currency, total_aum_millions=None):
    """(headers, rows) for AforePDFReport.add_table."""
    money = bool(total_aum_millions)
    headers = ["Asset Class", "% of Net Assets", "MoM", "YoY"]
    if money:
        headers.append(f"Value ({currency}M)")

    def delta(value):
        return "-" if value is None else f"{value:+.2f}"

    out = []
    for row in data["rows"]:
        line = [row["label"], f"{row['pct']:.2f}%", delta(row["mom"]), delta(row["yoy"])]
        if money:
            line.append(f"${row['pct'] / 100 * total_aum_millions:,.0f}M")
        out.append(line)

    total_line = ["TOTAL", f"{data['total']:.2f}%", "", ""]
    if money:
        total_line.append(f"${total_aum_millions:,.0f}M")
    out.append(total_line)
    return headers, out


def integrity_note(data):
    """A sentence for the page when the categories do not partition the book."""
    if abs(data["total"] - 100.0) <= GROUPS_TOTAL_TOLERANCE:
        return None
    return (
        f"WARNING: the top-level categories sum to {data['total']:.2f}%, not 100%. "
        "A SISET category was renamed or dropped; the composition below is incomplete."
    )
