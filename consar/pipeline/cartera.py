"""
CONSAR Cartera Composition — historical series
-----------------------------------------------
Pulls the system-wide SIEFORE portfolio composition by instrument category
(percent of net assets, monthly, Ene-2019 →) from CONSAR SISET md=18 and keeps
a local history JSON so the evolution is viewable without touching the portal.

Unlike the AUM download (Selenium), this works over plain HTTP: each SISET
Series page posts a JS-populated hidden field `seriesSeleccionadas` (values
with a TRAILING comma) plus the mes/año range fields; format "Excel" (ddlFormato=1)
returns an HTML table. The server's CSV/XML exports are broken server-side
(Excel COM error 80040154) — do not "upgrade" to them.

Every export returns the FULL series, so --update simply rewrites the history
file (self-healing against CONSAR revisions; no incremental state).

Usage (from the repo root, venv active):
    python3 -m consar.pipeline.cartera --update    # fetch all categories, rewrite history
    python3 -m consar.pipeline.cartera --report    # latest snapshot + deltas (text)
    python3 -m consar.pipeline.cartera --chart     # render PNG chart of the evolution
"""

import argparse
import datetime
import io
import json
import os
import re
import sys

import pandas as pd
import requests
from bs4 import BeautifulSoup

from consar.config import MONTHS_ES, PROJECT_DIR, retry

BASE = "https://www.consar.gob.mx/gobmx/aplicativo/siset/"
P = "ctl00$ContentPlaceHolder1$"

# md=18 ("Inversiones de las Siefores Generacionales") series pages, one per
# instrument category. Discovered 2026-07-13 from Enlace.aspx?md=18&nl=2.
# Category labels/series ids are read from each page at runtime — only the cd
# ids are pinned here.
CARTERA_CDS = [259, 271, 295, 283, 307, 319, 331, 343]

HISTORY_FILE = os.environ.get(
    "CARTERA_HISTORY_PATH",
    os.path.join(PROJECT_DIR, "../consar-siefore-history/consar_cartera_history.json"),
)

# Grouping rules for the report view (raw categories are stored as published).
GROUPS = {
    "Renta variable pública": ["Renta Variable Nacional", "Renta Variable Internacional"],
    "Renta fija": ["Deuda Privada Nacional", "Deuda Gubernamental", "Deuda Internacional"],
    "Mercancías": ["Mercancías"],
    "Estructurados": ["Estructurados"],
    "FIBRAS": ["FIBRAS"],
    "Otros Activos": ["Otros Activos"],
}

MONTHS_ES_HDR = {  # "Ene-2019" header → month number
    "ene": "01", "feb": "02", "mar": "03", "abr": "04", "may": "05", "jun": "06",
    "jul": "07", "ago": "08", "sep": "09", "oct": "10", "nov": "11", "dic": "12",
}


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    return s


def _discover_series(soup):
    """Category-level series on a Series.aspx page: every chkSerie whose label
    is not a 'Siefore …' detail row. Returns [(value, label)]."""
    out = []
    for b in soup.find_all("input", {"type": "checkbox"}):
        val = b.get("value")
        if not val:  # the selectAll box
            continue
        td = b.find_parent("td")
        label = ""
        if td:
            sib = td.find_next_sibling("td")
            label = (sib.get_text().strip() if sib else td.get_text().strip())
        if label and not label.startswith("Siefore"):
            out.append((val, label))
    return out


def _parse_export(html_text):
    """Parse the HTML-as-xls export → {label: {YYYY-MM: float}}."""
    table = pd.read_html(io.StringIO(html_text))[0]
    hdr_row = None
    for i in range(len(table)):
        if any(str(table.iloc[i, j]) == "Descripción del Concepto" for j in range(min(4, table.shape[1]))):
            hdr_row = i
            break
    if hdr_row is None:
        raise ValueError("export: header row 'Descripción del Concepto' not found")

    # month columns: "Ene-2019" style from hdr_row
    months = {}
    for j in range(table.shape[1]):
        cell = str(table.iloc[hdr_row, j]).strip()
        m = re.match(r"^([A-Za-z]{3})-(\d{4})$", cell)
        if m:
            mm = MONTHS_ES_HDR.get(m.group(1).lower())
            if mm:
                months[j] = f"{m.group(2)}-{mm}"

    series = {}
    for i in range(hdr_row + 1, len(table)):
        label = str(table.iloc[i, 1]).strip()
        if label in ("nan", "") or label.startswith(("Fuente", "Notas", "Cifras", "I)", "II)", "La Siefore")):
            continue
        if len(label) > 50:  # footnote continuation rows, not category labels
            continue
        vals = {}
        for j, period in months.items():
            raw = table.iloc[i, j]
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            vals[period] = round(v, 6)
        if vals:
            series[label] = vals
    return series


def _export_cd(s, cd):
    """One Series page: discover category series, post the export, parse."""
    url = f"{BASE}Series.aspx?cd={cd}&cdAlt=True"
    r = s.get(url, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    hidden = {i.get("name"): i.get("value", "") for i in soup.find_all("input", {"type": "hidden"}) if i.get("name")}
    cats = _discover_series(soup)
    if not cats:
        raise ValueError(f"cd={cd}: no category series found")

    mi, ai = hidden[P + "periodoMesI"], hidden[P + "periodoAñoI"]
    mf, af = hidden[P + "periodoMesF"], hidden[P + "periodoAñoF"]
    inv = {v: k for k, v in MONTHS_ES.items()}
    data = dict(hidden)
    data.update({
        P + "seriesSeleccionadas": ",".join(v for v, _ in cats) + ",",  # trailing comma required
        P + "mesInicialSeleccionado": mi, P + "añoInicialSeleccionado": ai,
        P + "mesFinalSeleccionado": mf, P + "añoFinalSeleccionado": af,
        P + "txtFechaIni": f"{inv.get(mi.zfill(2), 'Ene').capitalize()}/{ai}",
        P + "txtFechaFin": f"{inv.get(mf.zfill(2), 'Dic').capitalize()}/{af}",
        P + "ddlFormato": "1",   # "Excel" (HTML table). CSV/XML are broken server-side.
        P + "ddlDetalle": "1",   # Serie Seleccionada
        P + "btn_ExportaSeries": "Exportar",
    })
    r2 = s.post(url, data=data, timeout=90)
    r2.raise_for_status()
    if "vnd.ms-excel" not in r2.headers.get("content-type", ""):
        raise ValueError(f"cd={cd}: unexpected export response ({r2.headers.get('content-type')})")
    parsed = _parse_export(r2.content.decode("windows-1252", errors="replace"))
    return parsed, (f"{ai}-{mi.zfill(2)}", f"{af}-{mf.zfill(2)}")


def update():
    s = _session()
    categories, period = {}, (None, None)
    for cd in CARTERA_CDS:
        # SISET throttles bursts of exports — retry each cd with a pause.
        parsed, period = retry(lambda cd=cd: _export_cd(s, cd),
                               max_attempts=3, delay=30, description=f"cartera cd={cd}")
        for label, vals in parsed.items():
            if label in categories:
                print(f"⚠️  duplicate category label {label!r} (cd={cd}) — keeping first", file=sys.stderr)
                continue
            categories[label] = vals
        print(f"✓ cd={cd}: {', '.join(parsed)}")

    doc = {
        "source": "CONSAR SISET md=18 (Inversiones de las Siefores Generacionales), Sistema",
        "unit": "percent of net assets (Porcentaje de Inversión)",
        "period": {"from": period[0], "to": period[1]},
        "updated_at": datetime.date.today().isoformat(),
        "categories": categories,
    }
    os.makedirs(os.path.dirname(os.path.abspath(HISTORY_FILE)), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"\n💾 {len(categories)} categories, {period[0]} → {period[1]}")
    print(f"   {os.path.abspath(HISTORY_FILE)}")
    return doc


def _load():
    with open(HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def _grouped(doc):
    """{group: {period: pct}} using GROUPS; missing members are skipped."""
    out = {}
    for group, members in GROUPS.items():
        acc = {}
        for m in members:
            for period, v in doc["categories"].get(m, {}).items():
                acc[period] = acc.get(period, 0.0) + v
        if acc:
            out[group] = dict(sorted(acc.items()))
    return out


def report():
    doc = _load()
    groups = _grouped(doc)
    periods = sorted({p for g in groups.values() for p in g})
    latest = periods[-1]
    prev = periods[-2] if len(periods) > 1 else None
    yoy = f"{int(latest[:4]) - 1}{latest[4:]}"

    print(f"CONSAR cartera del sistema — {latest}  (fuente: SISET md=18, % de activos netos)")
    print(f"{'':28} {'ahora':>7} {'MoM':>7} {'YoY':>7}")
    for g, seriesd in groups.items():
        cur = seriesd.get(latest)
        if cur is None:
            continue
        mom = cur - seriesd[prev] if prev and prev in seriesd else None
        yy = cur - seriesd[yoy] if yoy in seriesd else None
        fmt = lambda d: f"{d:+.2f}" if d is not None else "  —  "
        print(f"  {g:<26} {cur:>6.2f}% {fmt(mom):>7} {fmt(yy):>7}")
    # raw detail for the three Louis tracks most
    print("\n  detalle:")
    for c in ("Renta Variable Internacional", "Estructurados", "FIBRAS"):
        v = doc["categories"].get(c, {}).get(latest)
        if v is not None:
            print(f"    {c:<30} {v:.2f}%")
    print(f"\n  historia: {doc['period']['from']} → {doc['period']['to']}  |  actualizado: {doc['updated_at']}")


def main():
    ap = argparse.ArgumentParser(description="CONSAR cartera composition history")
    ap.add_argument("--update", action="store_true", help="re-export all categories from SISET and rewrite the history file")
    ap.add_argument("--report", action="store_true", help="print latest snapshot + MoM/YoY deltas")
    ap.add_argument("--chart", action="store_true", help="render the evolution chart PNG (see cartera_chart.py)")
    args = ap.parse_args()
    if not (args.update or args.report or args.chart):
        ap.print_help(); return 1
    if args.update:
        update()
    if args.report:
        report()
    if args.chart:
        from consar.pipeline.cartera_chart import render
        render(_load(), _grouped(_load()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
