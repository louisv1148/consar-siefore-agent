"""
Cartera evolution chart — small multiples PNG.

Six panels (one entity each, per-panel y, shared x): the five grouped buckets
plus Renta Variable Internacional. Small multiples because the magnitudes span
~40x (Renta fija ~62% vs Mercancías ~1.4%) — one shared axis would flatten the
small series into noise.

Design per the dataviz method (validated 2026-07-13):
  palette #2a78d6 #1baf7a #eda100 #008300 #4a3aa7 #e34948 — CVD worst ΔE 24.2 PASS;
  aqua/yellow sub-3:1 contrast relieved by direct labels. Color follows the
  entity (fixed slot order, never re-cycled); titles/values wear ink tokens,
  never the series color; 2px lines, hairline grid, muted axes.
"""

import datetime
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from consar.config import PROJECT_DIR

OUT_PATH = os.path.join(PROJECT_DIR, "output", "cartera_evolution.png")

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

# (panel title, source, key, categorical slot color) — fixed order, color follows entity.
PANELS = [
    ("Renta variable pública", "group", "Renta variable pública", "#2a78d6"),
    ("Renta variable internacional", "raw", "Renta Variable Internacional", "#1baf7a"),
    ("Renta fija", "group", "Renta fija", "#eda100"),
    ("Estructurados", "group", "Estructurados", "#008300"),
    ("FIBRAS", "group", "FIBRAS", "#4a3aa7"),
    ("Mercancías", "group", "Mercancías", "#e34948"),
]


def render(doc, groups, out_path=OUT_PATH):
    fig, axes = plt.subplots(2, 3, figsize=(13, 7.4), dpi=200, facecolor=SURFACE)
    fig.subplots_adjust(left=0.055, right=0.985, top=0.86, bottom=0.09, hspace=0.52, wspace=0.24)

    for ax, (title, src, key, color) in zip(axes.flat, PANELS):
        seriesd = groups.get(key) if src == "group" else doc["categories"].get(key, {})
        pts = sorted(seriesd.items())
        xs = [datetime.date(int(p[:4]), int(p[5:7]), 1) for p, _ in pts]
        ys = [v for _, v in pts]

        ax.set_facecolor(SURFACE)
        for spine in ("top", "right", "left"):
            ax.spines[spine].set_visible(False)
        ax.spines["bottom"].set_color(BASELINE)
        ax.spines["bottom"].set_linewidth(0.8)
        ax.grid(axis="y", color=GRID, linewidth=0.7)
        ax.set_axisbelow(True)
        ax.tick_params(colors=MUTED, labelsize=8, length=0)

        ax.plot(xs, ys, color=color, linewidth=2, solid_capstyle="round")
        # end marker + direct value label (ink, not series color)
        ax.plot([xs[-1]], [ys[-1]], "o", color=color, markersize=5.5,
                markeredgecolor=SURFACE, markeredgewidth=1.2)
        ax.annotate(f"{ys[-1]:.1f}%", (xs[-1], ys[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center",
                    fontsize=9.5, fontweight="bold", color=INK)

        # identity: colored tick + ink title
        ax.set_title("     " + title, loc="left", fontsize=10.5, color=INK,
                     fontweight="bold", pad=8)
        ax.add_patch(plt.Rectangle((0.0, 1.06), 0.03, 0.055, transform=ax.transAxes,
                                   facecolor=color, edgecolor="none", clip_on=False))

        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.margins(x=0.02, y=0.18)
        ax.set_xlim(xs[0], xs[-1] + datetime.timedelta(days=270))  # room for end label
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:g}%")
        ax.locator_params(axis="y", nbins=4)

    latest = doc["period"]["to"]
    fig.suptitle("Cartera del sistema Afore — evolución mensual", x=0.055, y=0.965,
                 ha="left", fontsize=15, fontweight="bold", color=INK)
    fig.text(0.055, 0.905, f"% de activos netos · CONSAR SISET · Ene 2019 – {latest}"
             f" · actualizado {doc['updated_at']}", fontsize=9.5, color=INK_2)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"📈 chart → {out_path}")
    return out_path
