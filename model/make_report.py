#!/usr/bin/env python3
"""
make_report.py -- PDF report on the debt-service scenarios produced by run_scenarios.py.

Reads  data/inputs/<vintage>/*.csv (debt structure) and outputs/<vintage>/ALL_*.csv (scenario results)
Writes outputs/Debt_Service_Report.pdf  (charts rendered with matplotlib, assembled with reportlab)
"""
from __future__ import annotations
from pathlib import Path
import math
import polars as pl
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak,
                                KeepTogether)
import debt_model as dm
import run_scenarios as rs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # repository root (model/ sits one level down)
DATA = ROOT / "data"
OUT = ROOT / "outputs"
FIG = OUT / "figures"
FIG.mkdir(parents=True, exist_ok=True)
CC = ["US", "CA", "UK", "DE", "FR", "IT", "CN", "DK", "AU"]
NAME = {"US": "United States", "CA": "Canada", "UK": "United Kingdom", "DE": "Germany", "FR": "France",
        "IT": "Italy", "CN": "China", "DK": "Denmark", "AU": "Australia"}
BASE = dict(rate_scenario="market", deficit_scenario="holds", growth_scenario="base")
REP_COL = "#8e5bd0"                                    # the joint repression case

# ---- palette (reference instance of the dataviz method; light mode) -----------------------------
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"          # categorical slots 1-3
GRAY, GRAY2 = "#c3c2b7", "#8a8984"                     # de-emphasis
INK, INK2 = "#0b0b0b", "#52514e"
GRID = "#e8e7e3"
RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]   # ordinal blue ramp, steps 250..650
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
                     "legend.frameon": False, "figure.dpi": 110, "savefig.dpi": 200, "savefig.bbox": "tight"})


def save(fig, name):
    p = FIG / f"{name}.png"
    fig.savefig(p, facecolor="white")
    plt.close(fig)
    return p


# ==================================================================================================
# data
# ==================================================================================================
def load(vintage: int):
    wide = pl.read_csv(OUT / str(vintage) / "ALL_interest_to_gdp.csv")
    det = pl.read_csv(OUT / str(vintage) / "ALL_detail_paths.csv")
    ass = pl.read_csv(OUT / str(vintage) / "ALL_assumptions.csv")
    inputs = {cc: dm.load_inputs(DATA / "inputs" / str(vintage) / f"{cc}_debt_inputs.csv") for cc in CC}
    return wide, det, ass, inputs


def yrs(wide: pl.DataFrame) -> list[str]:
    return [c for c in wide.columns if c.isdigit()]


def row(wide, cc, **sc):
    f = wide.filter(pl.col("country") == cc)
    for k, v in sc.items():
        f = f.filter(pl.col(k) == v)
    return f.row(0, named=True)


def structure(inp: dm.ModelInputs) -> dict:
    """Debt-structure metrics from the input file."""
    bills = sum(b.base_outstanding or 0.0 for b in inp.buckets if not b.in_ladder)
    lad = {y: v for y, v in inp.ladder.items()}
    # the loader keeps only horizon years; re-read the file for the full ladder
    raw = pl.read_csv(DATA / "inputs" / str(inp.base_year) / f"{inp.meta['country_code']}_debt_inputs.csv",
                      comment_prefix="#", infer_schema=False)
    full = {int(float(p)): float(v) for s, i, p, v in raw.select("section", "item", "period", "value").iter_rows()
            if s == "maturity_ladder" and i == "amount"}
    cp = {int(float(p)): float(v) for s, i, p, v in raw.select("section", "item", "period", "value").iter_rows()
          if s == "maturity_ladder" and i == "coupon_pct"}
    coupon_total = sum(full.values())
    total = bills + coupon_total
    k = {y: y - inp.base_year for y in full}
    b13 = sum(v for y, v in full.items() if k[y] <= 3)
    b35 = sum(v for y, v in full.items() if 3 < k[y] <= 5)
    b510 = sum(v for y, v in full.items() if 5 < k[y] <= 10)
    b10 = sum(v for y, v in full.items() if k[y] > 10)
    wam = (bills * 0.5 + sum(v * (k[y] - 0.5) for y, v in full.items())) / total
    lad_cpn = sum(full[y] * cp[y] for y in full) / coupon_total
    return dict(bills=bills, total=total, buckets=[bills, b13, b35, b510, b10], wam=wam, ladder_coupon=lad_cpn,
                within3=(bills + b13) / total, mix={b.name: inp.mix[(b.name, inp.base_year + 1)] for b in inp.buckets})


# ==================================================================================================
# charts
# ==================================================================================================
def chart_dumbbell(wide, ys, path, vintage):
    y0, yH = ys[0], ys[-1]
    data = sorted([(cc, row(wide, cc, **BASE)[y0], row(wide, cc, **BASE)[yH]) for cc in CC], key=lambda r: r[2])
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    for i, (cc, a, b) in enumerate(data):
        ax.plot([a, b], [i, i], color=GRAY, lw=2, zorder=1)
        ax.scatter([a], [i], color=RAMP[0], s=46, zorder=3, edgecolor="white", linewidth=1.2)
        ax.scatter([b], [i], color=RAMP[3], s=46, zorder=3, edgecolor="white", linewidth=1.2)
        ax.text(max(a, b) + 0.12, i, f"{a:.1f} → {b:.1f}", va="center", fontsize=8, color=INK2)
    ax.set_yticks(range(len(data)), [NAME[c] for c, _, _ in data])
    ax.set_xlabel("interest expense, % of GDP")
    ax.set_xlim(left=min(0, min(min(a, b) for _, a, b in data) - 0.2))
    ax.scatter([], [], color=RAMP[0], label=y0); ax.scatter([], [], color=RAMP[3], label=f"{yH} baseline")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_title(f"Interest / GDP: {y0} versus {yH} baseline (market rates, deficit held, base growth)", loc="left", fontsize=10, color=INK)
    return save(fig, path)


def chart_range(wide, ys, path):
    yH = ys[-1]
    g = wide.group_by("country").agg(pl.col(yH).min().alias("lo"), pl.col(yH).max().alias("hi"))
    base = {cc: row(wide, cc, **BASE)[yH] for cc in CC}
    y0v = {cc: row(wide, cc, **BASE)[ys[0]] for cc in CC}
    d = sorted([(r["country"], r["lo"], r["hi"]) for r in g.to_dicts()], key=lambda r: base[r[0]])
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    for i, (cc, lo, hi) in enumerate(d):
        ax.plot([lo, hi], [i, i], color=RAMP[0], lw=6, solid_capstyle="round", zorder=1)
        ax.scatter([base[cc]], [i], color=RAMP[3], s=40, zorder=3, edgecolor="white", linewidth=1.2)
        ax.scatter([y0v[cc]], [i], color=INK, marker="|", s=120, zorder=4)
        ax.text(hi + 0.15, i, f"{lo:.1f} – {hi:.1f}", va="center", fontsize=8, color=INK2)
    ax.set_yticks(range(len(d)), [NAME[c] for c, _, _ in d])
    ax.set_xlabel(f"interest expense in {yH}, % of GDP")
    ax.plot([], [], color=RAMP[0], lw=6, label="range across all scenarios"); ax.scatter([], [], color=RAMP[3], label="baseline")
    ax.scatter([], [], color=INK, marker="|", s=120, label=f"today ({ys[0]})")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_title(f"How wide is the outcome space? {yH} interest / GDP across the scenario grid", loc="left", fontsize=10, color=INK)
    return save(fig, path)


def chart_small_multiples(wide, ys, path, vintage):
    fig, axes = plt.subplots(3, 3, figsize=(7.6, 6.6), sharex=True)
    xs = [int(y) for y in ys]
    ymax = wide.select(pl.max_horizontal(ys)).max().item()
    for ax, cc in zip(axes.flat, CC):
        sub = wide.filter(pl.col("country") == cc)
        lo = [sub[y].min() for y in ys]; hi = [sub[y].max() for y in ys]
        ax.fill_between(xs, lo, hi, color=RAMP[0], alpha=0.45, lw=0)
        for r in sub.iter_rows(named=True):
            ax.plot(xs, [r[y] for y in ys], color=GRAY, lw=0.6, alpha=0.6)
        b = row(wide, cc, **BASE)
        ax.plot(xs, [b[y] for y in ys], color=RAMP[3], lw=2)
        ax.set_title(NAME[cc], loc="left", fontsize=9, color=INK)
        ax.set_ylim(min(0, min(lo) - 0.2), math.ceil(ymax))
        ax.set_xticks([xs[0], xs[5], xs[-1]])
        ax.text(xs[-1], b[ys[-1]], f" {b[ys[-1]]:.1f}", fontsize=7.5, va="center", color=INK)
    axes[1, 0].set_ylabel("interest expense, % of GDP")
    fig.suptitle(f"Interest / GDP paths, {vintage} vintage: baseline (dark) within the full scenario envelope (band), every scenario in grey",
                 x=0.01, ha="left", fontsize=10, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return save(fig, path)


def chart_structure(st: dict, path, vintage):
    labels = ["Bills / <1y", "1–3y", "3–5y", "5–10y", ">10y"]
    order = sorted(CC, key=lambda c: st[c]["within3"], reverse=True)
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    left = [0.0] * len(order)
    for j, lab in enumerate(labels):
        vals = [st[c]["buckets"][j] / st[c]["total"] * 100 for c in order]
        ax.barh(range(len(order)), vals, left=left, color=RAMP[j], label=lab, height=0.62, edgecolor="white", linewidth=1.5)
        for i, (v, l) in enumerate(zip(vals, left)):
            if v > 9:
                ax.text(l + v / 2, i, f"{v:.0f}", ha="center", va="center", fontsize=7.5, color="white" if j >= 2 else INK)
        left = [l + v for l, v in zip(left, vals)]
    for i, c in enumerate(order):
        ax.text(101, i, f"WAM {st[c]['wam']:.1f}y", va="center", fontsize=8, color=INK2)
    ax.set_yticks(range(len(order)), [NAME[c] for c in order])
    ax.set_xlim(0, 118); ax.set_xlabel("% of marketable debt by remaining maturity")
    ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.45, -0.18), fontsize=8)
    ax.set_title(f"Debt structure ({vintage}): share of the stock repricing soon, and weighted average remaining maturity", loc="left", fontsize=10, color=INK)
    ax.grid(axis="y", visible=False)
    return save(fig, path)


def chart_issuance(st: dict, path, vintage):
    groups = [("Bills", ["Bills"]), ("2–3y", ["2Y", "3Y"]), ("5–7y", ["5Y", "7Y"]), ("10y", ["10Y"]), ("20–30y", ["20Y", "30Y"])]
    order = sorted(CC, key=lambda c: st[c]["mix"]["Bills"], reverse=True)
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    left = [0.0] * len(order)
    for j, (lab, keys) in enumerate(groups):
        vals = [sum(st[c]["mix"].get(k, 0) for k in keys) * 100 for c in order]
        ax.barh(range(len(order)), vals, left=left, color=RAMP[j], label=lab, height=0.62, edgecolor="white", linewidth=1.5)
        for i, (v, l) in enumerate(zip(vals, left)):
            if v > 9:
                ax.text(l + v / 2, i, f"{v:.0f}", ha="center", va="center", fontsize=7.5, color="white" if j >= 2 else INK)
        left = [l + v for l, v in zip(left, vals)]
    ax.set_yticks(range(len(order)), [NAME[c] for c in order]); ax.set_xlim(0, 100)
    ax.set_xlabel("% of gross issuance by original tenor (floating-rate notes excluded)")
    ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.45, -0.2), fontsize=8)
    ax.set_title(f"Issuance composition assumed going forward ({vintage})", loc="left", fontsize=10, color=INK)
    ax.grid(axis="y", visible=False)
    return save(fig, path)


def chart_cost_gap(det, inputs, path, vintage):
    """Average cost of the stock today vs cost of new issuance next year (market), per country."""
    d = []
    for cc in CC:
        inp = inputs[cc]
        f = det.filter((pl.col("country") == cc) & (pl.col("rate_scenario") == "market") & (pl.col("deficit_scenario") == "holds")
                       & (pl.col("growth_scenario") == "base")).sort("year")
        new1 = f.filter(pl.col("year") == inp.base_year + 1)["cost_new_issuance_pct"][0]
        d.append((cc, inp.cost0, new1))
    d.sort(key=lambda r: r[2] - r[1])
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    for i, (cc, a, b) in enumerate(d):
        ax.plot([a, b], [i, i], color=S2 if b > a else S3, lw=2.5, zorder=1, alpha=0.8)
        ax.scatter([a], [i], color=INK, s=40, zorder=3, edgecolor="white", linewidth=1.2)
        ax.scatter([b], [i], color=S2 if b > a else S3, s=40, zorder=3, edgecolor="white", linewidth=1.2)
        ax.text(max(a, b) + 0.1, i, f"{b - a:+.1f} pp", va="center", fontsize=8, color=INK2)
    ax.set_yticks(range(len(d)), [NAME[c] for c, _, _ in d]); ax.set_xlabel("% per year")
    ax.scatter([], [], color=INK, label="average cost of existing stock"); ax.plot([], [], color=S2, lw=2.5, label="new-issue cost above stock (repricing up)")
    ax.plot([], [], color=S3, lw=2.5, label="new-issue cost below stock (repricing down)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.18), ncol=3, fontsize=7.5)
    ax.set_title(f"The refinancing gap ({vintage}): average cost of the stock vs market cost of next year's issuance", loc="left", fontsize=10, color=INK)
    return save(fig, path)


def chart_country(cc, wide, det, ys, path, vintage, roles=None):
    xs = [int(y) for y in ys]
    sub = wide.filter(pl.col("country") == cc)
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.0))
    ax = axes[0]
    for r in sub.iter_rows(named=True):
        ax.plot(xs, [r[y] for y in ys], color=GRAY, lw=0.7, alpha=0.7)
    # (rate scenario, deficit scenario, growth scenario, label, colour): three curve cases at base growth with the deficit held,
    # plus the joint repression case (its own growth, deficit held)
    series = [(roles["base"], "holds", "base", "base curve (market)", S1), (roles["bear"], "holds", "base", "bear curve", S2),
              (roles["bull"], "holds", "base", "bull curve", S3),
              (roles["repression"], "holds", "repression", "repression (joint)" + (", ECB-bloc case" if cc in rs.BLOC_CONTINGENT else ""), REP_COL)]
    for name, dname, gname, lab, col in series:
        b = row(wide, cc, rate_scenario=name, deficit_scenario=dname, growth_scenario=gname)
        ax.plot(xs, [b[y] for y in ys], color=col, lw=2, label=lab, ls="--" if gname == "repression" and cc in rs.BLOC_CONTINGENT else "-")
        ax.text(xs[-1], b[ys[-1]], f" {b[ys[-1]]:.1f}", fontsize=7.5, va="center", color=INK)
    ax.set_title("Interest / GDP by curve case (grey: all 28 scenarios)", loc="left", fontsize=8.5, color=INK)
    ax.set_ylabel("% of GDP"); ax.legend(fontsize=7, loc="upper left"); ax.set_xticks([xs[0], xs[5], xs[-1]])
    ax = axes[1]
    for name, dname, gname, lab, col in series:
        f = det.filter((pl.col("country") == cc) & (pl.col("rate_scenario") == name) & (pl.col("deficit_scenario") == dname)
                       & (pl.col("growth_scenario") == gname)).sort("year")
        ax.plot(f["year"].to_list(), f["avg_cost_pct"].to_list(), color=col, lw=2)
        ax.text(f["year"][-1], f["avg_cost_pct"][-1], f" {f['avg_cost_pct'][-1]:.2f}", fontsize=7.5, va="center", color=INK)
    ax.set_title("Average cost of the debt stock, %", loc="left", fontsize=8.5, color=INK)
    ax.set_xticks([xs[0], xs[5], xs[-1]])
    fig.tight_layout()
    return save(fig, path)


def chart_rg(rg: dict, path):
    """Debt-stabilising primary balance (r-g)/(1+g) x d versus the actual primary balance."""
    order = sorted(CC, key=lambda c: rg[c]["req0"], reverse=True)
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    for i, cc in enumerate(order):
        r = rg[cc]
        ax.plot([r["req0"], r["reqH"]], [i, i], color=GRAY, lw=2, zorder=1)
        ax.scatter([r["req0"]], [i], color=RAMP[0], s=46, zorder=3, edgecolor="white", linewidth=1.2)
        ax.scatter([r["reqH"]], [i], color=RAMP[3], s=46, zorder=3, edgecolor="white", linewidth=1.2)
        ax.scatter([r["pb"]], [i], color=S2, marker="D", s=40, zorder=4, edgecolor="white", linewidth=1.0)
        ax.text(max(r["req0"], r["reqH"], r["pb"]) + 0.12, i, f"needs {r['req0']:+.1f} → {r['reqH']:+.1f}, runs {r['pb']:+.1f}", va="center", fontsize=7.5, color=INK2)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_yticks(range(len(order)), [NAME[c] for c in order]); ax.set_xlabel("primary balance, % of GDP (surplus > 0)")
    ax.scatter([], [], color=RAMP[0], label="required to stabilise debt/GDP today (r−g)/(1+g)·d")
    ax.scatter([], [], color=RAMP[3], label="required in 2036 (baseline cost and debt ratio)")
    ax.scatter([], [], color=S2, marker="D", label="actual primary balance today")
    ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.45, -0.16), ncol=2)
    ax.set_title("r versus g: the primary balance each country needs to stand still, against what it runs", loc="left", fontsize=10, color=INK)
    ax.set_xlim(left=min(-1.0, min(min(rg[c]["req0"], rg[c]["reqH"], rg[c]["pb"]) for c in CC) - 0.3))
    return save(fig, path)


def chart_backtest(w16, w26, path):
    d = []
    for cc in CC:
        s16 = row(w16, cc, **BASE)["2016"]
        p_base = row(w16, cc, **BASE)["2026"]
        p_real = row(w16, cc, rate_scenario="market", deficit_scenario="holds", growth_scenario="realized")["2026"]
        act = row(w26, cc, **BASE)["2026"]
        d.append((cc, s16, p_base, p_real, act))
    d.sort(key=lambda r: r[4])
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    for i, (cc, s16, pb, pr, act) in enumerate(d):
        ax.plot([min(pb, pr, act), max(pb, pr, act)], [i, i], color=GRAY, lw=2, zorder=1)
        ax.scatter([s16], [i], color=INK, marker="|", s=120, zorder=4)
        ax.scatter([pb], [i], color=RAMP[0], s=42, zorder=3, edgecolor="white", linewidth=1.2)
        ax.scatter([pr], [i], color=RAMP[2], s=42, zorder=3, edgecolor="white", linewidth=1.2)
        ax.scatter([act], [i], color=S2, s=48, zorder=5, edgecolor="white", linewidth=1.2)
        ax.text(max(pb, pr, act) + 0.1, i, f"actual {act:.1f} vs {pb:.1f} / {pr:.1f}", va="center", fontsize=7.5, color=INK2)
    ax.set_yticks(range(len(d)), [NAME[c] for c, *_ in d]); ax.set_xlabel("interest expense in 2026, % of GDP")
    ax.scatter([], [], color=INK, marker="|", s=120, label="2016 starting point")
    ax.scatter([], [], color=RAMP[0], label="2016 projection: 2016 growth, market rates, deficit held")
    ax.scatter([], [], color=RAMP[2], label="2016 projection: realized 2016–25 growth")
    ax.scatter([], [], color=S2, label="2026 actual (from the 2026 files)")
    ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.45, -0.16), ncol=2)
    ax.set_title("Back-test: what the 2016 snapshot implied for 2026, against where 2026 actually landed", loc="left", fontsize=10, color=INK)
    return save(fig, path)


# ==================================================================================================
# report
# ==================================================================================================
def build():
    w26, d26, a26, in26 = load(2026)
    w16, d16, a16, in16 = load(2016)
    ys26, ys16 = yrs(w26), yrs(w16)
    st26 = {cc: structure(in26[cc]) for cc in CC}
    st16 = {cc: structure(in16[cc]) for cc in CC}

    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=16, spaceAfter=8, textColor=colors.HexColor(INK))
    H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12.5, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor(INK))
    P = ParagraphStyle("P", parent=ss["BodyText"], fontSize=9.2, leading=13, spaceAfter=6, textColor=colors.HexColor(INK))
    SM = ParagraphStyle("SM", parent=P, fontSize=8, leading=10.5, textColor=colors.HexColor(INK2))
    B = ParagraphStyle("B", parent=P, leftIndent=10, bulletIndent=0, spaceAfter=3)

    def tbl(data, colw=None, size=8, head=True, align_right_from=1):
        t = Table(data, colWidths=colw, repeatRows=1 if head else 0)
        style = [("FONT", (0, 0), (-1, -1), "Helvetica", size), ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(INK)),
                 ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(GRAY2)), ("LINEBELOW", (0, -1), (-1, -1), 0.3, colors.HexColor(GRAY)),
                 ("ALIGN", (align_right_from, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f6f4")])]
        if head:
            style.append(("FONT", (0, 0), (-1, 0), "Helvetica-Bold", size))
        t.setStyle(TableStyle(style))
        return t

    def img(p, w=17 * cm):
        im = Image(str(p)); ratio = im.imageHeight / im.imageWidth
        im.drawWidth, im.drawHeight = w, w * ratio
        return im

    # ---- numbers used in the text ---------------------------------------------------------------
    yH = ys26[-1]
    kpi = {}
    for cc in CC:
        inp = in26[cc]; b = row(w26, cc, **BASE)
        sub = w26.filter(pl.col("country") == cc)
        rl = rs.curve_roles(inp)
        up = row(w26, cc, rate_scenario=rl["bear"], deficit_scenario="holds", growth_scenario="base")[yH]
        dn = row(w26, cc, rate_scenario=rl["bull"], deficit_scenario="holds", growth_scenario="base")[yH]
        rep = row(w26, cc, rate_scenario=rl["repression"], deficit_scenario="holds", growth_scenario="repression")[yH]
        cut = a26.filter((pl.col("country") == cc) & (pl.col("kind") == "policy_cut_pp"))["2027"][0]
        worse = row(w26, cc, rate_scenario="market", deficit_scenario="worsens", growth_scenario="base")[yH]
        slow = row(w26, cc, rate_scenario="market", deficit_scenario="holds", growth_scenario="low")[yH]
        kpi[cc] = dict(debt_gdp=inp.debt0 / inp.gdp0 * 100, cost=inp.cost0, i0=b["2026"], iH=b[yH], lo=sub[yH].min(), hi=sub[yH].max(),
                       d_rate=up - b[yH], d_bull=dn - b[yH], rep=rep, cut=cut, d_def=worse - b[yH], d_g=slow - b[yH], pd=inp.primary_deficit_current,
                       g=a26.filter((pl.col("country") == cc) & (pl.col("kind") == "growth") & (pl.col("scenario") == "base"))["2027"][0],
                       wam=st26[cc]["wam"], within3=st26[cc]["within3"] * 100, bills=st26[cc]["mix"]["Bills"] * 100)
    order = sorted(CC, key=lambda c: kpi[c]["iH"], reverse=True)

    story = []
    # ---- title ------------------------------------------------------------------------------------
    story += [Spacer(1, 3 * cm), Paragraph("Sovereign interest burdens under scenario", H1),
              Paragraph("Nine countries, projected ten years from the October 2026 snapshot, with a 2016 back-test", ParagraphStyle("sub", parent=P, fontSize=11, textColor=colors.HexColor(INK2))),
              Spacer(1, 0.6 * cm),
              Paragraph("Built from Bloomberg security-level pulls (every live central-government bond and bill), the on-the-run yield curves, "
                        "IMF fiscal balances and World Bank GDP. The engine rolls each country's debt forward bond by bond: maturing "
                        "paper and new borrowing are refinanced at the market-implied forward rate for the tenor the country actually "
                        "issues, the average cost of the stock updates, and interest expense is divided by nominal GDP. Each country is "
                        "run on a grid of 27 lever scenarios built around its own starting point: nominal growth at base and ±0.5 points, "
                        "the primary deficit held, drifting 1.5 points of GDP worse by year ten or (the bull's best case) turning into a surplus of at least 1% of GDP by "
                        "2030, and rates at market forwards, a bull curve (an AI boom then disinflation: "
                        "market forwards to 2030, then cuts to a low terminal curve by 2032) or a bear curve (inflation persists: no cuts, term premium rebuilt by 65–110 bp "
                        "at the long end), plus one joint financial-repression case (inflation 3–4%, the full cut held and the long end capped, nominal growth "
                        "+1 pt, deficit held).", P),
              Spacer(1, 0.4 * cm),
              Paragraph("Contents: 1 Headline results · 2 Reading the model · 3 Cross-country comparison · 4 Country pages · "
                        "5 r versus g: the Italy case study · 6 Back-test 2016→2026 · 7 Data and caveats", SM), PageBreak()]

    # ---- 1 headline -----------------------------------------------------------------------------------
    story += [Paragraph("1. Headline results", H1)]
    data = [["Country", "Debt/GDP", "Avg cost", "Int/GDP 2026", f"Int/GDP {yH}", f"Range {yH}", f"Repr. {yH}", "Δ bear", "Δ bull", "Δ deficit", "Δ growth", "Prim. def.", "WAM"]]
    for cc in order:
        k = kpi[cc]
        data.append([NAME[cc], f"{k['debt_gdp']:.0f}%", f"{k['cost']:.2f}%", f"{k['i0']:.2f}%", f"{k['iH']:.2f}%", f"{k['lo']:.1f}–{k['hi']:.1f}",
                     f"{k['rep']:.2f}%{'†' if cc in rs.BLOC_CONTINGENT else ''}",
                     f"{k['d_rate']:+.2f}", f"{k['d_bull']:+.2f}", f"+{k['d_def']:.2f}", f"+{k['d_g']:.2f}", f"{k['pd']:+.1f}%", f"{k['wam']:.1f}y"])
    story += [tbl(data, colw=[2.1 * cm, 1.2 * cm, 1.2 * cm, 1.4 * cm, 1.4 * cm, 1.6 * cm, 1.4 * cm, 1.1 * cm, 1.1 * cm, 1.2 * cm, 1.2 * cm, 1.2 * cm, 0.9 * cm], size=6.8),
              Paragraph("Debt = marketable central-government securities; avg cost = coupon-weighted cost of that stock; Int/GDP = modeled interest "
                        f"(avg cost × average debt) over nominal GDP; {yH} = baseline (market forwards, deficit held, base growth); range = min–max "
                        f"over the 28 scenarios (lever grid plus repression); Repr. = the joint financial-repression case (capped curve, nominal growth +1 pt, deficit held; "
                        "† = an ECB-bloc case for Germany, France and Italy, not a national option); the Δ columns are the change in "
                        f"{yH} Int/GDP from moving one lever off the baseline (bear = no cuts and a term-premium rebuild, bull = the AI-boom curve, "
                        "deficit = +1.5 pt of GDP worse by year 10, growth = −0.5 pt a year); "
                        "prim. def. = primary deficit, % of GDP (IMF general-government balance less modeled interest); WAM = weighted average remaining maturity.", SM)]
    top, bottom = order[0], order[-1]
    rising = [c for c in CC if kpi[c]["iH"] > kpi[c]["i0"] + 0.3]
    falling = [c for c in CC if kpi[c]["iH"] < kpi[c]["i0"] - 0.1]
    bear_worse = [c for c in CC if kpi[c]["d_rate"] > 0]; bear_better = [c for c in CC if kpi[c]["d_rate"] <= 0]
    most_rate = max(CC, key=lambda c: kpi[c]["d_rate"]); most_bull = min(CC, key=lambda c: kpi[c]["d_bull"]); most_def = max(CC, key=lambda c: kpi[c]["d_def"]); most_g = max(CC, key=lambda c: kpi[c]["d_g"])
    bullets = [
        f"<b>Three countries already pay 2–4% of GDP in interest and all three keep climbing on market pricing:</b> {NAME[order[0]]} "
        f"({kpi[order[0]]['i0']:.1f}% → {kpi[order[0]]['iH']:.1f}%), {NAME[order[1]]} ({kpi[order[1]]['i0']:.1f}% → {kpi[order[1]]['iH']:.1f}%) and "
        f"{NAME[order[2]]} ({kpi[order[2]]['i0']:.1f}% → {kpi[order[2]]['iH']:.1f}%). The rise is mechanical: the stock still carries coupons set in "
        "the 2010s and reprices toward today's curve as it rolls, and the primary deficit adds new debt on top.",
        f"<b>The deficit lever is largest where debt is already large relative to GDP;</b> {NAME[most_def]} gains the most from a 1.5-point "
        f"worsening of the primary balance (+{kpi[most_def]['d_def']:.2f} pp of GDP by {yH}).",
        ("<b>With no cuts in the bear case, the bear curve is worse than market everywhere.</b> The front end no longer offsets the long-end "
         "sell-off, so the bill-heavy programmes that a cut-and-steepen bear used to spare are now hit hardest: "
         + ", ".join(f"{NAME[c]} ({kpi[c]['d_rate']:+.1f} pp, bills {kpi[c]['bills']:.0f}% of issuance)" for c in sorted(CC, key=lambda c: -kpi[c]['d_rate'])[:3])
         if not bear_better else
         "<b>The bear curve is worse than market for most countries</b> but not all: in "
         + ", ".join(f"{NAME[c]} ({kpi[c]['d_rate']:+.1f} pp)" for c in bear_better) + " it still lowers the ratio; the largest hits are "
         + ", ".join(f"{NAME[c]} ({kpi[c]['d_rate']:+.1f} pp)" for c in sorted(CC, key=lambda c: -kpi[c]['d_rate'])[:3]))
        + ". The bull curve (market forwards to 2030, then cuts to a low terminal curve by 2032) helps most where the stock is large and short, because only debt "
        "rolled after 2031 gets the lower rates: "
        + ", ".join(f"{NAME[c]} {kpi[c]['d_bull']:+.1f}" for c in sorted(CC, key=lambda c: kpi[c]['d_bull'])[:3]) + " pp.",
        f"<b>Financial repression is the one case that holds the ratio near flat.</b> With the full cut held, the long end capped and nominal growth 1 pt higher, "
        f"{NAME[order[0]]} ends {yH} at {kpi[order[0]]['rep']:.1f}% against {kpi[order[0]]['iH']:.1f}% on market forwards, {NAME[order[1]]} at "
        f"{kpi[order[1]]['rep']:.1f}% and {NAME[order[2]]} at {kpi[order[2]]['rep']:.1f}%. Someone pays: a ten-year yield near 3.3% against inflation of "
        "3.5–4% is a negative real return to bondholders for a decade. For Germany, France and Italy it is an ECB-bloc case rather than a national choice, "
        "which is why it is also Italy's best cell in the whole model.",
        f"<b>Slower nominal growth hurts most where the ratio is highest:</b> −0.5 points of growth for ten years adds "
        f"+{kpi[most_g]['d_g']:.2f} pp in {NAME[most_g]} but only +{kpi[bottom]['d_g']:.2f} pp in {NAME[bottom]}. Growth is the denominator, so its "
        "effect scales with the level of the interest bill.",
        f"<b>{NAME[bottom]}</b> is the only country whose interest burden falls under market pricing "
        f"({kpi[bottom]['i0']:.2f}% → {kpi[bottom]['iH']:.2f}%): a primary surplus, a tiny stock and a curve close to the existing coupons."
        if kpi[bottom]["iH"] < kpi[bottom]["i0"] else f"<b>{NAME[bottom]}</b> has the lightest burden ({kpi[bottom]['i0']:.2f}% → {kpi[bottom]['iH']:.2f}%).",
        "<b>Low-burden countries are not risk-free in level terms but their sensitivities are small:</b> "
        + ", ".join(f"{NAME[c]} {kpi[c]['lo']:.1f}–{kpi[c]['hi']:.1f}%" for c in order[-4:]) + f" in {yH} across every scenario.",
    ]
    for b in bullets:
        story.append(Paragraph(b, B, bulletText="•"))
    story.append(PageBreak())

    # ---- 2 reading the model ------------------------------------------------------------------------
    story += [Paragraph("2. Reading the model", H1),
              Paragraph("<b>Engine.</b> Each year the government must refinance (a) the bonds in the measured maturity ladder and (b) the bonds the model "
                        "itself issued earlier that now mature, plus borrow the primary deficit and last year's interest. Gross issuance is split by the "
                        "country's estimated issuance composition and priced at that tenor's forward rate for that year. Average cost updates as "
                        "(old stock × old cost − maturing × its cost + issued × new cost) / new stock. Interest = cost × average debt; the ratio divides by GDP.", P),
              Paragraph("<b>Market-implied rates.</b> From the spot par curve: f(h,m) = [y(h+m)(h+m) − y(h)h]/m, with the term premium embedded today stripped "
                        "with the same operator and a static term premium (set equal to today's) added back. Floating-rate paper prices off expected overnight "
                        "rates with no premium.", P),
              Paragraph("<b>Rate scenarios are curve shapes set per country, not parallel shifts.</b> Bear and repression are specified as 2028 levels of the 1-, 2-, 10- and "
                        "30-year points (table below), reached by year two from today's spot; after that the bear keeps its shift over the market forward path "
                        "(so 'no cuts, +25 bp over market' holds all decade) while repression is held at its level, as a cap would be. Every other tenor the engine "
                        "prices moves with the nearest set points. <b>Bull (AI boom, then disinflation):</b> two phases. Through 2030 the capex boom keeps the curve on "
                        "market forwards; from 2031 the buildout is done, disinflation arrives and the central bank cuts, so the curve glides over 2031–32 to a terminal "
                        "level held through 2036 (United States: 2.0 / 2.2 / 3.0 / 3.5; France's spread over Bunds held). Only debt rolled after 2031 gets the lower "
                        "rates, so short-WAM issuers win in the back half and long-WAM issuers like the UK lock in phase-1 rates. "
                        "<b>Bear (inflation persists, higher for longer):</b> no cuts, the front end 25 bp over market, and the term premium rebuilds in proportion "
                        "to the fiscal position: 30-year +110 bp for the high-debt countries and +65 bp for the low-debt ones, with France +50 and Italy +75 bp of "
                        "spread loaded at ten years and beyond (United States: 4.9 / 5.0 / 5.9 / 6.5). <b>Repression (inflation 3–4%, curve engineered down):</b> "
                        "the full cut is held for the decade, a negative real policy rate, and the long end is capped with the term premium near zero, so the curve "
                        "is flat: ten-year about 1.3 pt over the one-year and thirty-year 0.3 pt over that (United States: 1.9 / 2.2 / 3.3 / 3.6). Repression is a "
                        "joint case: it always comes with nominal growth 1 pt above base (inflation, not real growth) and the deficit held, because repression "
                        "substitutes for consolidation; it is never crossed with the other levers. For Germany, France and Italy it is an ECB-bloc case, not a "
                        "national option (spreads compress to about 50 and 65 bp over Bunds); Australia gets a shallower cap because offshore ownership leaks into "
                        "the exchange rate. <b>China is the exception:</b> with yields at 1–2% its bull and repression are the yield cap holding (market forwards), "
                        "its base a developed-market steepening with the long end up 0.75–1 pt, and its bear the cap failing, a parallel +1.5 pt shift roughly back "
                        "to its 2016 levels. Its growth cases are 6 / 5 / 4 / 5%.", P),
              Paragraph("<b>Scenario definitions are relative to each country's own starting point</b> (table below), so a 'high growth' case for Denmark "
                        "is not the same number as for China. Base growth (2026 vintage) is the average of the 2016–25 nominal CAGR and the latest year's growth; "
                        "bull is base +1.0 through 2030 and then base for the US, UK, Canada and Australia (real +1.5 offset by lower inflation) or base +1.0 for the euro "
                        "members, Denmark and China, bear is base −0.5 and repression base +1.0. The deficit 'worsens' case glides linearly from today's primary deficit "
                        "to +1.5 points of GDP by year ten; 'improves' is the bull's best-case budget: a glide from today's balance to a primary surplus of at "
                        "least 1% of GDP by 2030 (1.5 points better where the balance is already a surplus), held thereafter, the revenue harvest.", P)]
    data = [["Country", "Base growth", "Bull p1→p2 / Bear / Repr.", "Prim. deficit", "Improves / Worsens", "Base 2Y / 10Y / 30Y (2028)", "Bull (2036)", "Bear (2028)", "Repression (2028)"]]
    def rt(cc, scen, ten, y="2028"):
        return a26.filter((pl.col("country") == cc) & (pl.col("kind") == f"rate_{ten}") & (pl.col("scenario") == scen))[y][0]
    for cc in CC:
        rl = rs.curve_roles(in26[cc])
        g = a26.filter((pl.col("country") == cc) & (pl.col("kind") == "growth"))
        gb, glo, ghi, grp = (g.filter(pl.col("scenario") == k)["2027"][0] for k in ("base", "low", "high", "repression"))
        ghi2 = g.filter(pl.col("scenario") == "high")["2036"][0]
        pdv = kpi[cc]["pd"]
        data.append([NAME[cc], f"{gb:.2f}%", f"{ghi:.1f}→{ghi2:.1f} / {glo:.1f} / {grp:.1f}", f"{pdv:+.2f}%", f"{rs.bull_deficit_target(pdv):+.1f} / {pdv+1.5:+.1f}",
                     " / ".join(f"{rt(cc, rl['base'], t):.1f}" for t in ("2Y", "10Y", "30Y")),
                     " / ".join(f"{rt(cc, rl['bull'], t, '2036'):.1f}" for t in ("2Y", "10Y", "30Y")),
                     " / ".join(f"{rt(cc, rl['bear'], t):.1f}" for t in ("2Y", "10Y", "30Y")),
                     " / ".join(f"{rt(cc, rl['repression'], t):.1f}" for t in ("2Y", "10Y", "30Y")) + ("†" if cc in rs.BLOC_CONTINGENT else "")])
    story += [tbl(data, colw=[1.9 * cm, 1.2 * cm, 2.9 * cm, 1.3 * cm, 1.8 * cm, 2.3 * cm, 1.9 * cm, 1.9 * cm, 2.1 * cm], size=6.4),
              Paragraph("Primary deficits come from IMF general-government balances, which include regional and local government and accrual items; they "
                        "therefore run wider than the central-government balance that matches the bond stock modeled here. This is most visible for the "
                        "United States (5.2% here against roughly 3% on a federal cash basis) and China (7.5%). Because the deficit is a lever in the grid, "
                        "read the 'improves' column as closer to a central-government reading for those two.", SM), PageBreak()]

    # ---- 3 cross-country ------------------------------------------------------------------------------
    gap = {}
    for cc in CC:
        f = d26.filter((pl.col("country") == cc) & (pl.col("rate_scenario") == "market") & (pl.col("deficit_scenario") == "holds")
                       & (pl.col("growth_scenario") == "base") & (pl.col("year") == in26[cc].base_year + 1))
        gap[cc] = (in26[cc].cost0, f["cost_new_issuance_pct"][0])
    gsorted = sorted(CC, key=lambda c: gap[c][1] - gap[c][0], reverse=True)
    story += [Paragraph("3. Cross-country comparison", H1),
              img(chart_dumbbell(w26, ys26, "dumbbell26", 2026)),
              Paragraph("Under market pricing with deficits held and base growth, interest/GDP rises in every country except Denmark. The move is largest where "
                        "two things coincide: a large stock relative to GDP and a wide gap between the coupons on the existing stock and today's curve "
                        f"(next chart). France stands out because the gap is wide ({gap['FR'][0]:.1f}% on the stock against {gap['FR'][1]:.1f}% for new money) on a "
                        f"{kpi['FR']['debt_gdp']:.0f}%-of-GDP stock with a {kpi['FR']['pd']:.1f}% primary deficit.", P),
              img(chart_cost_gap(d26, in26, "costgap26", 2026)),
              Paragraph("The refinancing gap is the single best predictor of the slope of the interest path: every country with new-issue cost above the "
                        f"stock's average cost sees the ratio climb even before adding new debt. The widest gaps are {NAME[gsorted[0]]} "
                        f"(+{gap[gsorted[0]][1]-gap[gsorted[0]][0]:.1f} pp), {NAME[gsorted[1]]} (+{gap[gsorted[1]][1]-gap[gsorted[1]][0]:.1f}) and "
                        f"{NAME[gsorted[2]]} (+{gap[gsorted[2]][1]-gap[gsorted[2]][0]:.1f}). Italy's gap is small because its stock already carries post-2022 "
                        f"coupons; China is the only country refinancing below its average cost ({gap['CN'][1]-gap['CN'][0]:+.1f} pp), which is why its ratio "
                        "rises only through new borrowing. A wide gap on a small stock (Denmark, Australia) matters far less than a moderate gap on a large one.", P),
              PageBreak(),
              img(chart_range(w26, ys26, "range26")),
              Paragraph("The band is the full envelope of the 28 scenarios (the 27 lever combinations plus the joint repression case, which sets the floor). Its width is roughly proportional to the level: "
                        "a country at 1% of GDP cannot move far in ten years, a country at 3–4% can move by several points in either direction. Note that even the "
                        "most favourable scenario leaves the United States, France and Italy above their 2026 level or close to it.", P),
              PageBreak(),
              img(chart_small_multiples(w26, ys26, "sm26", 2026)),
              Paragraph(f"Read the slope, not just the end point. France and the United States climb steadily because they combine a wide refinancing gap, "
                        f"a short structure and a primary deficit; Italy starts higher but rises by {kpi['IT']['iH']-kpi['IT']['i0']:.1f} points against "
                        f"France's {kpi['FR']['iH']-kpi['FR']['i0']:.1f}, because its stock has already repriced and it runs a primary surplus; Denmark is flat. "
                        "Grey lines are the 28 individual scenarios (lever grid plus repression); the band is their envelope.", P),
              PageBreak(),
              img(chart_structure(st26, "structure26", 2026)),
              Paragraph("Structure determines speed. The United States and China roll more than half of their stock within three years, so a rate change "
                        "reaches the average cost within an electoral cycle; the UK, with a weighted average remaining maturity above a decade, "
                        "reprices slowly, which cuts both ways: it is insulated from today's higher curve but will carry it for decades once locked in.", P),
              img(chart_issuance(st26, "issuance26", 2026)),
              Paragraph("Issuance composition is estimated from the lines opened in the last two years (Australia: from the maturity profile). It governs how fast "
                        "the stock converges to the curve and how much term premium is paid. Bills dominate the US, Canadian and French programmes; the UK, Germany and "
                        "China spread issuance across the curve, and China issues no bills to speak of.", P), PageBreak()]

    # ---- 4 country pages -----------------------------------------------------------------------------
    story += [Paragraph("4. Country pages", H1),
              Paragraph("Each page: interest/GDP under market forwards, the bear curve (orange), the bull curve (green) and the joint repression case (violet; dashed where "
                        "it is an ECB-bloc case) with every other scenario in grey, the average cost of the stock under the same four cases, the full "
                        f"{yH} grid for base growth, and the key structural numbers.", P)]
    for cc in CC:
        k = kpi[cc]; s = st26[cc]; inp = in26[cc]
        mat = w26.filter((pl.col("country") == cc) & (pl.col("growth_scenario") == "base")).pivot(on="rate_scenario", index="deficit_scenario", values=yH)
        rl = rs.curve_roles(inp)
        cols = [rl["bull"], rl["base"], rl["bear"]]
        data = [[f"{yH} Int/GDP, base growth", "bull curve", "base curve", "bear curve"]]
        for dname in ["improves", "holds", "worsens"]:
            r = mat.filter(pl.col("deficit_scenario") == dname).row(0, named=True)
            data.append([f"deficit {dname}"] + [f"{r[c]:.2f}%" for c in cols])
        glow = row(w26, cc, rate_scenario="market", deficit_scenario="holds", growth_scenario="low")[yH]
        ghigh = row(w26, cc, rate_scenario="market", deficit_scenario="holds", growth_scenario="high")[yH]
        data.append([f"growth low / high (market, held)", f"{glow:.2f}%", "", f"{ghigh:.2f}%"])
        data.append([f"repression (joint{', ECB-bloc case' if cc in rs.BLOC_CONTINGENT else ''})", "", f"{k['rep']:.2f}%", ""])
        facts = [["Debt / GDP", f"{k['debt_gdp']:.0f}%"], ["Average cost of stock", f"{k['cost']:.2f}%"],
                 ["Ladder coupon (bonds only)", f"{s['ladder_coupon']:.2f}%"], ["Bills share of stock", f"{s['bills']/s['total']*100:.0f}%"],
                 ["Repricing within 3 years", f"{k['within3']:.0f}%"], ["Weighted avg maturity", f"{k['wam']:.1f} years"],
                 ["Primary deficit (IMF basis)", f"{k['pd']:+.2f}% GDP"], ["Base nominal growth", f"{k['g']:.2f}%"],
                 ["Bills share of issuance", f"{k['bills']:.0f}%"]]
        levers = sorted([("a 1.5-pt worse deficit", k["d_def"]), ("0.5 pt less growth", k["d_g"])], key=lambda x: -x[1])
        trend = "rises" if k["iH"] > k["i0"] + 0.05 else ("falls" if k["iH"] < k["i0"] - 0.05 else "is flat")
        text = (f"Interest/GDP {trend} from {k['i0']:.2f}% to {k['iH']:.2f}% by {yH} on market pricing with the deficit held "
                f"({k['pd']:+.1f}% of GDP) and {k['g']:.1f}% nominal growth. The full grid spans {k['lo']:.1f}%–{k['hi']:.1f}%. "
                f"Of the fiscal and growth levers, {levers[0][0]} matters more ({levers[0][1]:+.2f} pp) than {levers[1][0]} ({levers[1][1]:+.2f}). "
                f"The bull curve (market forwards to 2030, then cuts to a low terminal curve by 2032) is worth {k['d_bull']:+.2f} pp; the bear curve "
                f"(no cuts, term premium rebuilt) {k['d_rate']:+.2f} pp, with {k['bills']:.0f}% of issuance in bills setting how fast either reaches the stock. "
                f"Financial repression (capped curve, nominal growth +1 pt, deficit held{', an ECB-bloc case' if cc in rs.BLOC_CONTINGENT else ''}) "
                f"ends {yH} at {k['rep']:.2f}%. "
                f"{k['within3']:.0f}% of the stock reprices within three years (WAM {k['wam']:.1f} years), so the average cost moves "
                f"{'quickly' if k['within3'] > 45 else 'gradually'} toward the curve.")
        block = [Paragraph(f"{NAME[cc]}", H2), Paragraph(text, P), img(chart_country(cc, w26, d26, ys26, f"c_{cc}", 2026, rl)),
                 Table([[tbl(data, colw=[4.4 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm], size=7.8), tbl(facts, colw=[4.0 * cm, 2.3 * cm], size=7.8, head=False)]],
                       colWidths=[11.0 * cm, 6.4 * cm], style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]), PageBreak()]
        story += block

    # ---- 5 r versus g ---------------------------------------------------------------------------------------
    rg = {}
    for cc in CC:
        k = kpi[cc]; inp = in26[cc]
        f = d26.filter((pl.col("country") == cc) & (pl.col("rate_scenario") == "market") & (pl.col("deficit_scenario") == "holds")
                       & (pl.col("growth_scenario") == "base") & (pl.col("year") == inp.base_year + 10)).row(0, named=True)
        g = k["g"]; d0 = k["debt_gdp"] / 100; dH = f["debt_pct_gdp"] / 100
        rg[cc] = dict(req0=(k["cost"] - g) / (1 + g / 100) * d0, reqH=(f["avg_cost_pct"] - g) / (1 + g / 100) * dH, pb=-k["pd"],
                      r0=k["cost"], rH=f["avg_cost_pct"], g=g, d0=d0 * 100, dH=dH * 100)
    it = rg["IT"]; us = rg["US"]; fr = rg["FR"]
    above_now = [c for c in CC if rg[c]["r0"] > rg[c]["g"]]
    above_H = [c for c in CC if rg[c]["rH"] > rg[c]["g"]]
    story += [Paragraph("5. r versus g: the Italy case study", H1),
              Paragraph("The debt ratio obeys Δd ≈ (r − g)/(1 + g) · d − pb: when the average cost of the debt (r) exceeds nominal growth (g), a primary "
                        "surplus is needed just to keep debt/GDP flat, and the requirement scales with the debt ratio. The chart puts each country's required "
                        "primary balance, today and at the 2036 baseline, next to what it actually runs.", P),
              img(chart_rg(rg, "rg26")),
              Paragraph(f"<b>Today only {', '.join(NAME[c] for c in above_now)} {'has' if len(above_now) == 1 else 'have'} r above g.</b> Italy's average cost "
                        f"({it['r0']:.2f}%) exceeds its base nominal growth ({it['g']:.2f}%) on a {it['d0']:.0f}%-of-GDP stock, so it needs a primary surplus of about "
                        f"{it['req0']:.1f}% of GDP to stand still; it runs {it['pb']:+.1f}%, which is why its interest ratio rises by only "
                        f"{kpi['IT']['iH']-kpi['IT']['i0']:.1f} points over the decade against {kpi['FR']['iH']-kpi['FR']['i0']:.1f} for France from a lower start. "
                        "That margin is thin and it is the product of three decades of surpluses that still left the ratio higher than in 1992, "
                        "because (r − g) consumed them: the treadmill. The requirement binds hardest in recessions, when g falls, spreads widen and d jumps "
                        "together, which makes fiscal policy structurally pro-cyclical and is one reason Italian real growth has been so weak for so long.", P),
              Paragraph(f"<b>By 2036 the baseline puts {len(above_H)} countries past the threshold</b> ({', '.join(NAME[c] for c in above_H)}). The United States "
                        f"reaches an average cost of {us['rH']:.2f}% against {us['g']:.2f}% growth, France {fr['rH']:.2f}% against {fr['g']:.2f}%. France's required "
                        f"surplus rises from {fr['req0']:+.1f}% to {fr['reqH']:+.1f}% of GDP while it currently runs {fr['pb']:+.1f}%: the gap between required and "
                        "actual is the widest in the sample. Italy is not the outlier in this report; it is the preview.", P),
              Paragraph("<b>What changes when the debt is in your own currency.</b> For the United States, the United Kingdom, Canada, Australia and (in its own "
                        "way) China, r &gt; g never forces default: the adjustment runs through inflation and the exchange rate. Surprise nominal growth raises g, "
                        "erodes the real stock and is paid by bondholders through negative real returns, which is exactly what the 2016→2026 back-test in the next "
                        "section shows for the US and UK, where ratios were held down by inflation while deficits blew out. The joint cases make the link between "
                        "r and g explicit: the bear case pairs the higher curve with lower nominal growth (inflation that persists without real growth), and the "
                        "repression case is this paragraph turned into numbers: the curve is held below inflation, nominal growth runs 1 pt higher, the ratio "
                        "stays near flat and bondholders absorb the loss. The lever grid holds g fixed across curve cases; read the joint cases for the correlated "
                        "outcomes.", P),
              Paragraph("<b>Italy borrows in what is effectively a foreign currency.</b> There is no unilateral inflation, no devaluation and no unconditional buyer of "
                        "last resort, so the adjustment must be real (surpluses, internal devaluation) and restructuring is a genuine tail. That is why BTPs carry a "
                        "credit spread and Treasuries and gilts do not: the euro converts inflation risk into credit risk. Crucially, Italian r can rise for reasons "
                        "unconnected to Italian g (a Bund sell-off, French contagion, domestic politics), so the bear cell is the one case in this grid where the "
                        "shock arrives with no growth offset at all. For Italy that cell should be read at face value, and the (r − g) distribution is not just wider "
                        "than for an own-currency sovereign but skewed. The mitigating factor is also the euro: it is why Italy's r is about 3% and not the 8–12% of "
                        "the lira era, and since 2012 the ECB's conditional backstop (OMT, flexible PEPP reinvestments, TPI) has fenced off the self-fulfilling "
                        "run, with roughly a quarter of the BTP stock on the Eurosystem's balance sheet. The price of that insurance is externally enforced "
                        "fiscal discipline. Repression, by contrast, is not Italy's to choose: it is an ECB-bloc case, and it is also Italy's best cell in the model, "
                        f"{kpi['IT']['rep']:.1f}% of GDP in {yH} against {kpi['IT']['iH']:.1f}% on market forwards.", P),
              Paragraph("<b>Net reading.</b> For an own-currency sovereign, interest/GDP above growth is a chronic condition eroded slowly through inflation and paid by "
                        "savers; for Italy it is a latent-acute one: lower average cost, mandatory surpluses, no inflation exit, and a fat tail that only the ECB's "
                        "umbrella keeps closed. Expressed as a trade, the same thesis sits in the long end and the currency for the US, and in the spread for Italy.", P),
              PageBreak()]

    # ---- 6 back-test ---------------------------------------------------------------------------------------
    story += [Paragraph("6. Back-test: the 2016 snapshot projected to 2026", H1),
              Paragraph("The same engine was run on each country's 2016 bond stock, the 2016 curve and 2016 term premia, with the 2016 primary deficit "
                        "held and either the 2016 growth rate or the growth that actually materialised over 2016–25. The comparison is against the "
                        "2026 files' own starting ratio, i.e. the same cost × debt / GDP definition, not reported budget interest.", P),
              img(chart_backtest(w16, w26, "backtest"))]
    data = [["Country", "2016 start", "Proj. 2026 (2016 growth)", "Proj. 2026 (realized growth)", "Actual 2026", "Miss (realized)"]]
    for cc in CC:
        s16 = row(w16, cc, **BASE)["2016"]; pb = row(w16, cc, **BASE)["2026"]
        pr = row(w16, cc, rate_scenario="market", deficit_scenario="holds", growth_scenario="realized")["2026"]; act = row(w26, cc, **BASE)["2026"]
        data.append([NAME[cc], f"{s16:.2f}%", f"{pb:.2f}%", f"{pr:.2f}%", f"{act:.2f}%", f"{act-pr:+.2f} pp"])
    story += [tbl(data, colw=[2.8 * cm, 2 * cm, 3.6 * cm, 3.8 * cm, 2.2 * cm, 2.4 * cm], size=8),
              Paragraph("<b>What the back-test says.</b> Seven of nine countries ended 2026 with a heavier interest burden than the 2016 forward curve implied, "
                        "even after crediting the strong nominal growth of 2021–23 that inflation delivered. The 2016 curves priced rates staying near zero "
                        "(Europe) or low (US, Canada) for the whole decade; the 2022–23 repricing added 200–400 bp to every curve and the model has no way "
                        "to anticipate that from market data. The deficits also ran well above the 2016 baseline in the US, UK, France and Italy during the pandemic. "
                        "Denmark is the exception that proves the mechanism: a primary surplus and a stock that shrank made the projection accurate. "
                        "China was over-predicted because its rates fell rather than rose.", P),
              Paragraph("<b>How to use this.</b> The market-implied path is a central estimate conditional on the curve, not a forecast of the curve. The scenario "
                        "band around it is the honest range, and the 2016 experience says outcomes beyond the +100 bp case are not tail events. When reading "
                        "the 2026 projections, weight the bear-curve and deficit-worse cells accordingly for countries with short maturity structures.", P), PageBreak()]

    # ---- 6 data & caveats --------------------------------------------------------------------------------
    story += [Paragraph("7. Data and caveats", H1)]
    for t in [
        "<b>Debt stock.</b> Marketable central-government bonds and bills from Bloomberg SRCH pulls dated 16 Oct 2026 (2016 pulls: 31 Mar for the UK and Canada, 30 Jun for Australia, "
        "30 Sep for the US, 31 Dec for the others). Domestic-market issues only, deduplicated by ISIN; central-bank holdings remain inside the stock. "
        "The US pull excludes TIPS and FRNs; Australia's and the UK's linkers are included at real coupon plus 2 points of inflation accrual.",
        "<b>Average cost.</b> Amount-weighted coupon of the coupon stock blended with bills at the 1-year yield. This is a coupon measure, not budget interest: "
        "it understates inflation uplift on linkers beyond the 2-point allowance and ignores premium/discount amortisation.",
        "<b>Curves.</b> On-the-run yields from the Bloomberg file for the US, Canada, UK, Germany, France and Italy; policy rates and 1-year yields for all countries, "
        "and the China, Denmark and Australia curves, from public sources dated 12–21 Oct 2026 (Denmark 1Y/5Y/30Y and Australia 1Y/30Y interpolated). "
        "2016 curves from the user's table (long bond mapped to 30 years, 1Y interpolated).",
        "<b>Term premia.</b> 5Y and 10Y from the macro workbook; other tenors shaped on the US profile. For France, Italy, Germany and Denmark the workbook's premium is "
        "a euro rate premium plus the sovereign spread versus Bunds; the spread (France 151 bp, Italy 112 bp, Denmark −18 bp) is applied flat across tenors so that it "
        "is carried, not stripped, in the forwards. Static premium equals implied. China set to zero.",
        "<b>Issue dates and issuance composition.</b> Not in the pull. Issue dates were estimated from market conventions (US 10-year notes mature on the 15th of Feb/May/Aug/Nov, "
        "3-years on the 15th of other months; Canada's benchmark calendar; German tickers; Italian and Danish tenor labels) and from the chronological order of CUSIP, "
        "SEDOL and ISIN numbers anchored on the 2016 pull. The composition is the lines opened in the last two years; for Australia, which taps old lines, it is inferred "
        "from the maturity profile. The US estimate reproduces the known programme split within a few points.",
        "<b>Deficits and GDP.</b> IMF general-government balances (2026 projections) and World Bank nominal GDP (2026 extrapolated from 2025 at the 2025 growth rate). "
        "The primary deficit used as 'current' equals the IMF deficit less the model's own interest, so it is wider than a central-government measure.",
        "<b>Model simplifications.</b> Interest is lagged one year in the financing identity; cohorts mature exactly at their nominal tenor; linkers and floaters are "
        "carried at coupon; no buybacks, switches or central-bank remittances; calendar-year buckets for all countries regardless of fiscal year.",
    ]:
        story.append(Paragraph(t, P))
    story += [Spacer(1, 0.4 * cm), Paragraph("Files: data/inputs/2026 and data/inputs/2016 (model inputs, one per country, with per-file notes), outputs/2026 and outputs/2016 "
                                             "(ALL_interest_to_gdp.csv, ALL_detail_paths.csv, ALL_assumptions.csv), debt_model.py (engine), run_scenarios.py (assumptions), "
                                             "build_inputs.py (data pipeline).", SM)]

    pdf = OUT / "Debt_Service_Report.pdf"
    doc = SimpleDocTemplate(str(pdf), pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title="Sovereign interest burdens under scenario", author="debt_model")

    def footer(canvas, doc_):
        canvas.saveState(); canvas.setFont("Helvetica", 7.5); canvas.setFillColor(colors.HexColor(INK2))
        canvas.drawString(1.8 * cm, 1.0 * cm, "Sovereign interest burdens under scenario — nine countries, 2026 and 2016 vintages")
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.0 * cm, f"page {doc_.page}"); canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return pdf


if __name__ == "__main__":
    print("wrote", build())
