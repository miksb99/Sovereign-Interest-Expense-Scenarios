#!/usr/bin/env python3
"""
scenario_lines.py -- four joint cases per country (bull / base / bear / repression) of interest expense / GDP, 2026-2036,
sovereign plus tier 1, and the charts that compare them.

Joint case = sovereign levers moved together (growth, primary deficit, curve) + the tier-1 settings of the same name where a
country has tier-1 debt (CA, AU, CN, DE, FR, IT).  Where tier 1 exists the sovereign runs on the central-only primary deficit
(general-government deficit less the tier-1 sector's own balance) so sub-national borrowing is counted once; tier-1 interest
is divided by the GDP path of the same scenario.

   bull       : AI boom then disinflation, two phases -- 2027-30 market forwards, growth base +1, primary balance gliding to a
                surplus of at least 1% of GDP by 2030 (held after), tier 1 middle settings; from 2031 the curve glides (over
                2031-32) to a low terminal level, growth back to base (US/UK/CA/AU) or base +1 (others), tier 1 tight spread and
                longer WAM
   base       : base growth, deficit held, market forwards, tier 1 at its middle pace
   bear       : inflation persists -- nominal growth -0.5, deficit worsens 1.5, no cuts and term premium rebuilds (30Y +110 bp
                high-debt / +65 low-debt, FR +50 / IT +75 of spread); tier 1 at its fastest pace, shorter WAM, stressed spread
   repression : inflation 3-4% with the curve engineered down -- nominal growth +1.0, deficit HELD, full cut held and the long
                end capped (10Y ~ 1Y + 1.3); tier 1 at its middle pace, longer WAM, tight spread.  Joint only; an ECB-bloc case
                for Germany, France and Italy.
   China      : growth 6 / 5 / 4 / 5; bull and repression = the cap holds (market), base = DM-style steepening, bear = the cap
                fails (parallel +1.5); LGFV bank/trust loans included in tier 1.

Outputs: outputs/2026/SCENARIO_LINES.csv, SCENARIO_ASSUMPTIONS.csv, SCENARIO_CAGR.csv, SCENARIO_R_MINUS_G.csv,
SCENARIO_SENSITIVITY.csv, outputs/Scenario_Lines.pdf and outputs/Scenario_Summary.pdf
"""
from __future__ import annotations
import math
from pathlib import Path
import polars as pl
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Image, Table, TableStyle, PageBreak
import debt_model as dm
import run_scenarios as rs
import tier1_overlay as t1
import then_vs_now as tvn

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # repository root (model/ sits one level down)
DATA = ROOT / "data"
OUT = ROOT / "outputs"
FIG = OUT / "figures"
FIG.mkdir(parents=True, exist_ok=True)
CC = ["US", "FR", "IT", "UK", "CN", "AU", "CA", "DE", "DK"]
NAME = {"US": "United States", "CA": "Canada", "UK": "United Kingdom", "DE": "Germany", "FR": "France", "IT": "Italy",
        "CN": "China", "DK": "Denmark", "AU": "Australia"}
CASES = rs.CASES
COL = {"bull": "#1baf7a", "base": "#2a78d6", "bear": "#eb6834", "repression": "#8e5bd0", "monetary": "#c48a1a"}
INK, INK2, GRID, GRAY2 = "#0b0b0b", "#52514e", "#e8e7e3", "#8a8984"
GROWTH, DEFICIT = rs.CASE_GROWTH, rs.CASE_DEFICIT
SHORT = {"bull": "Bull (AI boom)", "base": "Base (market)", "bear": "Bear (higher for longer)", "repression": "Repression (capped curve)",
         "monetary": "Monetary dominance (US only)"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
                     "grid.linewidth": 0.6, "axes.axisbelow": True, "legend.frameon": False, "figure.dpi": 110, "savefig.dpi": 200, "savefig.bbox": "tight"})


def bloc(cc: str, case: str) -> bool:
    return case == "repression" and cc in rs.BLOC_CONTINGENT


def main() -> None:
    inputs26 = {cc: dm.load_inputs(DATA / "inputs" / "2026" / f"{cc}_debt_inputs.csv") for cc in CC}
    inputs16 = {cc: dm.load_inputs(DATA / "inputs" / "2016" / f"{cc}_debt_inputs.csv") for cc in t1.T1_COUNTRIES}
    blocks = t1.prepare_blocks(inputs16)
    t1_bal = t1.t1_balance_share(blocks, {cc: inputs26[cc].gdp0 for cc in t1.T1_COUNTRIES})

    rows, arows = [], []
    ctx = {}                                                   # per-country objects for the lever decomposition
    for cc in CC:
        inp = inputs26[cc]
        has_t1 = cc in t1.T1_COUNTRIES
        tenors = sorted(set(t1.t1_tenors(blocks, cc)) | {t1.tenor_label(bl["T"] + d) for bl in blocks if bl["cc"] == cc for d in (2, -2)}) if has_t1 else []   # incl. the ±1y WAM sensitivity tenors
        pd_gg = inp.primary_deficit_current
        pd_c = pd_gg - t1_bal.get(cc, 0.0)
        inp.primary_deficit_current = pd_c                      # deficit cases glide from (and target relative to) the central figure
        st = rs.settings_for(inp, 2026, tenors)
        scen = dm.resolve_scenarios(inp, st["growth"], st["deficit"], st["mix"], st["rates"])
        roles = rs.curve_roles(inp)
        mats = {c: dm.build_rate_matrix(inp, st["rates"].get(roles[c]), tenors) for c in rs.cases_for(cc)}
        ctx[cc] = dict(inp=inp, scen=scen, mats=mats, blocks=[b for b in blocks if b["cc"] == cc and b["fiscal"]], has_t1=has_t1)
        for case in rs.cases_for(cc):
            sov = dm.project(inp, mats[case], scen.growth[GROWTH[case]], scen.deficit[rs.case_deficit(cc, case)], scen.issuance[rs.case_mix(cc, case)])
            gdp = {r["year"]: r["nominal_gdp"] for r in sov}
            t1_int = {r["year"]: 0.0 for r in sov}
            t1_stock = {r["year"]: 0.0 for r in sov}
            t1_desc = []
            y1, yH = t1.YEARS[0], t1.YEARS[-1]
            agg = dict(stock=0.0, g1=0.0, w1=0.0, wH=0.0, s1=0.0, sH=0.0, g_lgb=None, g_lgfv=None)
            for bl in ctx[cc]["blocks"]:
                gp, T, sp = t1.t1_settings(bl, case)
                for r in t1.roll(bl["stock"], bl["cost0"], gp, T, t1.t1_rate(mats[case], T, sp)):
                    t1_int[r["year"]] += r["interest"]; t1_stock[r["year"]] += r["stock"]
                wam_s = f"{T[y1] / 2:.1f}y" if abs(T[y1] - T[yH]) < 1e-9 else f"{T[y1] / 2:.1f}→{T[yH] / 2:.1f}y"
                sp_s = f"+{sp[y1]*100:.0f}bp" if abs(sp[y1] - sp[yH]) < 1e-9 else f"+{sp[y1]*100:.0f}→{sp[yH]*100:.0f}bp"
                t1_desc.append(f"{bl['block'].split('_', 1)[1]}: growth {gp[y1]:+.1f}%, WAM {wam_s}, {sp_s}")
                s_ = bl["stock"]; agg["stock"] += s_; agg["g1"] += gp[y1] * s_; agg["w1"] += T[y1] / 2 * s_; agg["wH"] += T[yH] / 2 * s_
                agg["s1"] += sp[y1] * s_; agg["sH"] += sp[yH] * s_
                if bl["block"] == "CN_LGB":
                    agg["g_lgb"] = gp[y1]
                if bl["block"].startswith("CN_LGFV") and agg["g_lgfv"] is None:
                    agg["g_lgfv"] = gp[y1]
            t1_sum = {k_: (v / agg["stock"] if agg["stock"] > 0 and k_ in ("g1", "w1", "wH", "s1", "sH") else v) for k_, v in agg.items()}
            for r in sov:
                y = r["year"]
                tot_int, tot_debt = r["interest_expense"] + t1_int[y], r["debt"] + t1_stock[y]
                blended = tot_int / tot_debt * 100 if tot_debt > 0 else 0.0          # debt can be fully retired (Denmark's bull)
                g_assumed = r["ngdp_growth_pct"] if r["ngdp_growth_pct"] is not None else inp.ngdp_growth_current
                rows.append(dict(country=cc, case=case, year=y, sovereign_pct_gdp=r["interest_pct_gdp"], tier1_pct_gdp=t1_int[y] / gdp[y] * 100,
                                 total_pct_gdp=r["interest_pct_gdp"] + t1_int[y] / gdp[y] * 100, sovereign_debt_pct_gdp=r["debt_pct_gdp"],
                                 tier1_debt_pct_gdp=t1_stock[y] / gdp[y] * 100, nominal_gdp=gdp[y],
                                 sovereign_avg_cost=r["avg_cost_pct"], blended_avg_cost=blended,
                                 ngdp_growth_assumed=g_assumed, r_minus_g=blended - g_assumed,
                                 g_minus_intgdp=inp.ngdp_growth_current - (r["interest_pct_gdp"] + t1_int[y] / gdp[y] * 100)))
            g = scen.growth[GROWTH[case]]; d = scen.deficit[rs.case_deficit(cc, case)]
            r28 = {t: mats[case][(t, 2028)] for t in ("1Y", "2Y", "10Y", "30Y")}
            r36 = {t: mats[case][(t, 2036)] for t in ("1Y", "2Y", "10Y", "30Y")}
            sp_ = rs.growth_split(inp, 2026, scen.growth)[GROWTH[case]]
            arows.append(dict(country=cc, case=case, nominal_gdp_growth_pct=g[t1.YEARS[0]], nominal_gdp_growth_2036=g[t1.YEARS[-1]],
                              real_growth_pct=sp_[t1.YEARS[0]][0], inflation_pct=sp_[t1.YEARS[0]][1], real_growth_2036=sp_[t1.YEARS[-1]][0], inflation_2036=sp_[t1.YEARS[-1]][1],
                              nominal_gdp_growth_avg=sum(g.values()) / len(g),
                              primary_deficit_2027=d[t1.YEARS[0]], primary_deficit_2030=d[2030], primary_deficit_2036=d[t1.YEARS[-1]],
                              gg_primary_deficit_2026=pd_gg, central_primary_deficit_used=pd_c if has_t1 else pd_gg,
                              curve=roles[case], bloc_contingent=bloc(cc, case),
                              rate_1Y_2028=r28["1Y"], rate_2Y_2028=r28["2Y"], rate_10Y_2028=r28["10Y"], rate_30Y_2028=r28["30Y"],
                              rate_1Y_2036=r36["1Y"], rate_2Y_2036=r36["2Y"], rate_10Y_2036=r36["10Y"], rate_30Y_2036=r36["30Y"],
                              tier1="; ".join(t1_desc) if t1_desc else "none",
                              t1_stock_pct_gdp=t1_sum["stock"] / inp.gdp0 * 100, t1_growth_yr1=t1_sum["g1"], t1_wam_yr1=t1_sum["w1"], t1_wam_2036=t1_sum["wH"],
                              t1_spread_yr1_bp=t1_sum["s1"] * 100, t1_spread_2036_bp=t1_sum["sH"] * 100, t1_growth_lgb=t1_sum["g_lgb"], t1_growth_lgfv=t1_sum["g_lgfv"]))
    lines = pl.DataFrame(rows); ass = pl.DataFrame(arows)
    lines.write_csv(OUT / "2026" / "SCENARIO_LINES.csv"); ass.write_csv(OUT / "2026" / "SCENARIO_ASSUMPTIONS.csv")

    def val(c, case, yr, col="total_pct_gdp"):
        return lines.filter((pl.col("country") == c) & (pl.col("case") == case) & (pl.col("year") == yr))[col][0]

    # ---- cross-country stacked bars, one chart per case -------------------------------------------------------------
    def chart_bars(case):
        order = sorted(CC, key=lambda c: val(c, case, 2036), reverse=True)
        fig, ax = plt.subplots(figsize=(10.5, 4.6))
        w = 0.38
        handles = []
        for j, (yr, alpha) in enumerate(((2026, 0.5), (2036, 1.0))):
            sov = [val(c, case, yr, "sovereign_pct_gdp") for c in order]
            t1v = [val(c, case, yr, "tier1_pct_gdp") for c in order]
            xs = [i + (j - 0.5) * w for i in range(len(order))]
            hatch = ["//" if bloc(c, case) else None for c in order]
            for x, a, b, h in zip(xs, sov, t1v, hatch):
                ax.bar([x], [a], width=w - 0.04, color=COL[case], alpha=alpha, edgecolor="white", linewidth=1.2, hatch=h)
                ax.bar([x], [b], width=w - 0.04, bottom=a, color="#8a8984", alpha=alpha, edgecolor="white", linewidth=1.2, hatch=h)
                ax.text(x, a + b + 0.06, f"{a + b:.1f}", ha="center", fontsize=7.5, color=INK)
            handles += [Patch(facecolor=COL[case], alpha=alpha, label=f"sovereign {yr}"), Patch(facecolor="#8a8984", alpha=alpha, label=f"tier 1 {yr}")]
        top = max(max(val(c, case, 2036) for c in CC), max(val(c, case, 2026) for c in CC))
        for i, c in enumerate(order):
            v0, v1 = val(c, case, 2026), val(c, case, 2036)
            cagr = ((v1 / v0) ** 0.1 - 1) * 100 if v0 > 0 and v1 > 0 else float("nan")
            ax.text(i, top * 1.12, f"CAGR {cagr:+.1f}%", ha="center", fontsize=7.5, color=INK2)
        ax.set_ylim(0, top * 1.22)
        if case == "repression":
            handles.append(Patch(facecolor="white", edgecolor=GRAY2, hatch="//", label="hatched = ECB-bloc case, not a national choice"))
        ax.set_xticks(range(len(order)), [NAME[c] for c in order], fontsize=8.5); ax.set_ylabel("interest expense, % of GDP")
        ax.legend(handles=handles, ncol=5, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.1)); ax.grid(axis="x", visible=False)
        ax.set_title(f"{SHORT[case]}: interest / GDP in 2026 (light) and 2036 (dark), tier 1 stacked in grey; CAGR = growth of the total ratio 2026–36",
                     loc="left", fontsize=10, color=INK)
        pth = FIG / f"bars_{case}.png"; fig.savefig(pth, facecolor="white"); plt.close(fig); return pth
    bar_pngs = {case: chart_bars(case) for case in CASES}

    def dot(ax, x, i, c, case):
        if bloc(c, case):
            ax.scatter([x], [i], facecolor="none", edgecolor=COL[case], marker="D", s=110, zorder=6, linewidth=1.6)   # open diamond so a coincident dot stays visible
        else:
            ax.scatter([x], [i], color=COL[case], s=64, zorder=3, edgecolor="white", linewidth=1.2)

    def range_legend(ax, today_label):
        for case in CASES:
            ax.scatter([], [], color=COL[case], s=64, label=SHORT[case])
        ax.scatter([], [], facecolor="none", edgecolor=COL["repression"], marker="D", s=70, linewidth=1.6, label="repression, ECB-bloc case")
        ax.scatter([], [], facecolor="white", edgecolor=INK, marker="o", s=44, label=today_label)
        ax.legend(ncol=3, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.1))

    def chart_range(year=2036):
        """Per country: a stacked bar of the four cases' nominal-growth assumptions (bull = its 2027-36 average) and, just to its
        left, a vertical column of dots with each case's interest / GDP in `year`.  One percentage axis for both."""
        g = {c: {case: ass.filter((pl.col("country") == c) & (pl.col("case") == case))["nominal_gdp_growth_avg"][0] for case in CASES} for c in CC}
        v = {c: {case: val(c, case, year) for case in rs.cases_for(c)} for c in CC}
        groups = [("United States & China", ["US", "CN"]), ("Commonwealth", ["CA", "AU"]), ("Europe", ["UK", "DE", "FR", "IT"])]   # Denmark left out
        order = [c for _, cs in groups for c in cs]
        fig, ax = plt.subplots(figsize=(12.5, 6.2))
        bw, dx = 0.34, 0.30                                    # bar width; dots sit this far left of the bar centre
        stack_order = ["bear", "base", "bull", "repression"]  # legend order; each bar stacks its cases from the lowest growth up
        for i, c in enumerate(order):
            xb, xd = i + 0.12, i + 0.12 - dx
            bottom = 0.0
            for case in sorted(CASES, key=lambda k: g[c][k]):      # incremental stack: each segment = extra growth over the case below it
                h = g[c][case] - bottom
                if h > 1e-9:
                    ax.bar([xb], [h], bottom=bottom, width=bw, color=COL[case], alpha=0.55, edgecolor="white", linewidth=1.2, zorder=2)
                    if h >= 0.3:
                        ax.text(xb, bottom + h / 2, f"{g[c][case]:.1f}", ha="center", va="center", fontsize=7.5, color=INK)
                    bottom = g[c][case]
            lo, hi = min(v[c].values()), max(v[c].values())
            ax.plot([xd, xd], [lo, hi], color="#dcdbd6", lw=4, zorder=1, solid_capstyle="round")
            for case in rs.cases_for(c):
                ax.scatter([xd], [v[c][case]], color=COL[case], s=64, zorder=4, edgecolor="white", linewidth=1.2)
            ax.text(xd - 0.09, hi, f"{hi:.1f}", ha="right", va="center", fontsize=7.5, color=INK2)
            ax.text(xd - 0.09, lo, f"{lo:.1f}", ha="right", va="center", fontsize=7.5, color=INK2)
        ax.set_xticks([i + 0.12 - dx / 2 for i in range(len(order))], [NAME[c] for c in order], fontsize=9)
        ax.set_xlim(-0.75, len(order) - 0.3)
        ytop = max(max(v[c].values()) for c in order) * 1.08
        ax.set_ylim(0, ytop * 1.06)
        pos = 0
        for gi, (label, cs) in enumerate(groups):                        # group headers and separators
            ax.text(pos + (len(cs) - 1) / 2 - 0.03, ytop, label, ha="center", va="bottom", fontsize=9, color=INK2)
            pos += len(cs)
            if gi < len(groups) - 1:
                ax.axvline(pos - 0.5 - 0.03, color=GRID, lw=1.0, ls="--", zorder=0)
        ax.set_ylabel("per cent of GDP (dots)  |  nominal GDP growth, % a year (bars)")
        ax.grid(axis="x", visible=False)
        bar_h = [Patch(facecolor=COL[case], alpha=0.55, label=SHORT[case]) for case in stack_order]
        dot_h = [plt.Line2D([], [], marker="o", ls="", color=COL[case], markersize=8, label=SHORT[case]) for case in CASES + ["monetary"]]
        leg1 = ax.legend(handles=bar_h, title="Bars: nominal GDP growth assumed, % a year", ncol=4, fontsize=8, title_fontsize=8.5,
                         loc="upper center", bbox_to_anchor=(0.5, -0.08), alignment="left")
        ax.add_artist(leg1)
        ax.legend(handles=dot_h, title=f"Dots: interest expense / GDP in {year}, sovereign plus tier 1", ncol=4, fontsize=8, title_fontsize=8.5,
                  loc="upper center", bbox_to_anchor=(0.5, -0.17), alignment="left")
        ax.set_title(f"How interest expense over GDP can develop by {year}", loc="left", fontsize=11.5, color=INK)
        pth = FIG / "range_2036.png"; fig.savefig(pth, facecolor="white"); plt.close(fig); return pth
    range_png = chart_range()

    def chart_growth():
        g = {c: {case: ass.filter((pl.col("country") == c) & (pl.col("case") == case))["nominal_gdp_growth_avg"][0] for case in CASES} for c in CC}
        latest = {c: inputs26[c].ngdp_growth_current for c in CC}
        order = sorted(CC, key=lambda c: g[c]["base"])
        fig, ax = plt.subplots(figsize=(9.5, 5.4))
        for i, c in enumerate(order):
            lo, hi = min(g[c].values()), max(g[c].values())
            ax.plot([lo, hi], [i, i], color="#dcdbd6", lw=5, zorder=1, solid_capstyle="round")
            ax.scatter([latest[c]], [i], facecolor="none", edgecolor=INK, marker="o", s=52, zorder=5, linewidth=1.2)
            for case in CASES:
                dot(ax, g[c][case], i, c, case)
            ax.text(min(lo, latest[c]) - 0.12, i, f"{lo:.1f}", ha="right", va="center", fontsize=7.5, color=INK2)
            ax.text(max(hi, latest[c]) + 0.12, i, f"{hi:.1f}", ha="left", va="center", fontsize=7.5, color=INK2)
            ax.text(g[c]["base"], i + 0.3, f"{g[c]['base']:.1f}", ha="center", va="bottom", fontsize=7.5, color=COL["base"])
        ax.set_yticks(range(len(order)), [NAME[c] for c in order], fontsize=9)
        ax.set_xlabel("nominal GDP growth assumed, average over 2027–36, % a year (bull: base +1 to 2030, then base or base +1)")
        ax.set_xlim(min(min(min(g[c].values()), latest[c]) for c in CC) - 0.8, max(max(max(g[c].values()), latest[c]) for c in CC) + 0.8); ax.set_ylim(-0.7, len(order) - 0.3)
        range_legend(ax, "latest year (2025)")
        ax.set_title("Nominal GDP growth assumed in each case, against the latest observed year", loc="left", fontsize=10, color=INK)
        ax.grid(axis="y", visible=False); ax.tick_params(axis="y", length=0)
        pth = FIG / "range_growth.png"; fig.savefig(pth, facecolor="white"); plt.close(fig); return pth
    growth_png = chart_growth()

    def chart_rg():
        order = sorted(CC, key=lambda c: val(c, "base", 2036, "g_minus_intgdp"))
        out = {}
        for case in CASES:
            fig, ax = plt.subplots(figsize=(11, 5.6))
            now = [val(c, case, 2026, "g_minus_intgdp") for c in order]
            fut = [val(c, case, 2036, "g_minus_intgdp") for c in order]
            r_now = [val(c, case, 2026, "blended_avg_cost") for c in order]
            r_fut = [val(c, case, 2036, "blended_avg_cost") for c in order]
            w = 0.38
            xs0 = [i - w / 2 for i in range(len(order))]; xs1 = [i + w / 2 for i in range(len(order))]
            ax.bar(xs0, now, width=w - 0.04, color="#b9b8b2", label="latest growth − interest/GDP, 2026", edgecolor="white", linewidth=1)
            ax.bar(xs1, fut, width=w - 0.04, color=COL[case], label="latest growth − interest/GDP, 2036", edgecolor="white", linewidth=1,
                   hatch=["//" if bloc(c, case) else None for c in order] if case == "repression" else None)
            for x, v, inside in [(x, v, INK) for x, v in zip(xs0, now)] + [(x, v, "white") for x, v in zip(xs1, fut)]:
                if abs(v) >= 0.6:
                    ax.text(x, 0.12 if v >= 0 else -0.12, f"{v:+.1f}", ha="center", va="bottom" if v >= 0 else "top", fontsize=8, color=inside)
                else:
                    ax.text(x, v + (0.1 if v >= 0 else -0.1), f"{v:+.1f}", ha="center", va="bottom" if v >= 0 else "top", fontsize=7.5, color=INK2)
            ax.scatter(xs0, r_now, facecolor="white", edgecolor=INK, s=50, zorder=4, linewidth=1.2, label="average interest rate, 2026")
            ax.scatter(xs1, r_fut, color=INK, s=50, zorder=4, label="average interest rate, 2036")
            ax.axhline(0, color=INK2, lw=0.8)
            ax.set_xticks(range(len(order)), [NAME[c] for c in order], fontsize=10)
            ax.set_ylabel("percentage points"); ax.grid(axis="x", visible=False)
            lo = min(min(now), min(fut)) - 0.8; hi = max(max(r_now), max(r_fut), max(now), max(fut)) + 0.8
            ax.set_ylim(lo, hi)
            ax.legend(ncol=4, fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.08))
            ax.set_title(f"{SHORT[case]}: latest nominal GDP growth (2025) minus interest expense / GDP (bars; below zero = the interest bill "
                         f"outruns today's growth) and the average interest rate on the debt (dots)"
                         + ("; hatched = ECB-bloc case" if case == "repression" else ""), loc="left", fontsize=10, color=INK, wrap=True)
            fig.tight_layout()
            pth = FIG / f"rg_{case}.png"; fig.savefig(pth, facecolor="white"); plt.close(fig); out[case] = pth
        return out
    rg_pngs = chart_rg()

    # ---- sensitivity: a one-unit move in each assumption from the BASE case, independent of the scenario magnitudes ---------
    #   sovereign: +1 pp a year nominal growth; +1 pt of GDP primary deficit held every year; +100 bp parallel shift of the whole
    #              curve from 2027 on
    #   tier 1   : +1 pp a year stock growth; +1 year WAM (issue tenor +2); +100 bp spread
    #   Each is measured symmetrically, (f(+1) - f(-1)) / 2, on the 2036 interest / GDP ratio (sovereign plus tier 1).
    #   The curve is shocked one KEY TENOR at a time (the tenors the sovereign issues at): +100 bp on that tenor, fading linearly to zero
    #   at the neighbouring key tenors, so tier-1 blocks priced at odd maturities move too.  The key-rate shocks add up to the parallel
    #   shift, which is kept as a check.
    KEYS = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
    KEY_TAU = [dm.parse_tenor(t) for t in KEYS]
    LEVERS = [("sov_growth", "nominal growth, +1 pp/yr"), ("sov_deficit", "primary deficit, +1 pt GDP")] + \
             [(f"kr_{t}", f"{t} rate, +100 bp" + (" (bills)" if t == "1Y" else "")) for t in KEYS] + \
             [("t1_growth", "tier-1 debt growth, +1 pp/yr"), ("t1_wam", "tier-1 WAM, +1 year"), ("t1_spread", "tier-1 spread, +100 bp")]
    GREENS = ["#cdeedd", "#a9e2c7", "#83d4af", "#5fc498", "#3db584", "#1baf7a", "#148a60", "#0d6647"]
    LCOL = {"sov_growth": "#2a78d6", "sov_deficit": "#eb6834", "t1_growth": "#eda100", "t1_wam": "#e87ba4", "t1_spread": "#4a3aa7",
            **{f"kr_{t}": c for t, c in zip(KEYS, GREENS)}}
    UNIT = {k_: 1.0 for k_, _ in LEVERS}

    def key_weight(lab, key):
        """Triangular key-rate weight of tenor `lab` for a bump at `key` (1 at the key, 0 at the neighbouring keys, flat beyond the ends)."""
        tau, i = dm.parse_tenor(lab), KEYS.index(key)
        lo = KEY_TAU[i - 1] if i > 0 else None; hi = KEY_TAU[i + 1] if i + 1 < len(KEYS) else None; k = KEY_TAU[i]
        if tau <= k:
            return 1.0 if (lo is None or tau <= lo and i == 0) else (0.0 if tau <= lo else (tau - lo) / (k - lo))
        return 1.0 if hi is None else (0.0 if tau >= hi else (hi - tau) / (hi - k))

    def total_2036_shocked(cc, g=0.0, d=0.0, r=0.0, tg=0.0, wam=0.0, sp=0.0, kr=None):
        k = ctx[cc]; inp, scen, mat = k["inp"], k["scen"], k["mats"]["base"]
        growth = {y: v + g for y, v in scen.growth["base"].items()}
        deficit = {y: v + d for y, v in scen.deficit["holds"].items()}
        rates = {key: (v + r * (key_weight(key[0], kr) if kr else 1.0) if key[1] > inp.base_year else v) for key, v in mat.items()}
        sov = dm.project(inp, rates, growth, deficit)
        last = sov[-1]; gdp = last["nominal_gdp"]; t1i = 0.0
        for bl in k["blocks"]:
            gp0, T0, sp0 = t1.t1_settings(bl, "base")
            gp = {y: v + tg for y, v in gp0.items()}
            T = {y: v + 2 * wam for y, v in T0.items()}
            spp = {y: v + sp for y, v in sp0.items()}                 # spreads are in percentage points: sp = 1.0 is +100 bp
            t1i += t1.roll(bl["stock"], bl["cost0"], gp, T, t1.t1_rate(rates, T, spp))[-1]["interest"]
        return last["interest_pct_gdp"] + t1i / gdp * 100

    shares, srows, sens, parallel = {}, [], {}, {}
    ARG = {"sov_growth": "g", "sov_deficit": "d", "t1_growth": "tg", "t1_wam": "wam", "t1_spread": "sp"}
    for cc in CC:
        base_v = total_2036_shocked(cc)
        s = {}
        for key, _ in LEVERS:
            if key.startswith("t1") and not ctx[cc]["has_t1"]:
                continue
            if key.startswith("kr_"):
                up = total_2036_shocked(cc, r=1.0, kr=key[3:]); dn = total_2036_shocked(cc, r=-1.0, kr=key[3:])
            else:
                up = total_2036_shocked(cc, **{ARG[key]: UNIT[key]}); dn = total_2036_shocked(cc, **{ARG[key]: -UNIT[key]})
            s[key] = (up - dn) / 2
        parallel[cc] = (total_2036_shocked(cc, r=1.0) - total_2036_shocked(cc, r=-1.0)) / 2
        tot_abs = sum(abs(v) for v in s.values())
        sens[cc] = s; shares[cc] = {k_: abs(v) / tot_abs for k_, v in s.items()}
        srows.append(dict(country=cc, base_2036_pct_gdp=base_v, curve_parallel_pp_per_100bp=parallel[cc], **{f"{k_}_pp_per_unit": v for k_, v in s.items()},
                          **{f"{k_}_share": shares[cc][k_] for k_ in s}))
    pl.DataFrame(srows).write_csv(OUT / "2026" / "SCENARIO_SENSITIVITY.csv")

    # the pies group the eight tenors into three curve segments; the table keeps every tenor
    SEG = [("front", "front end (1–3Y), +100 bp", ["1Y", "2Y", "3Y"], "#a9e2c7"), ("belly", "belly (5–7Y), +100 bp", ["5Y", "7Y"], "#1baf7a"),
           ("long", "long end (10–30Y), +100 bp", ["10Y", "20Y", "30Y"], "#0d6647")]
    PIE = [("sov_growth", "nominal growth, +1 pp/yr", LCOL["sov_growth"]), ("sov_deficit", "primary deficit, +1 pt GDP", LCOL["sov_deficit"])] + \
          [(f"seg_{k_}", lab, col) for k_, lab, _, col in SEG] + \
          [("t1_growth", "tier-1 debt growth, +1 pp/yr", LCOL["t1_growth"]), ("t1_wam", "tier-1 WAM, +1 year", LCOL["t1_wam"]), ("t1_spread", "tier-1 spread, +100 bp", LCOL["t1_spread"])]
    grouped = {}
    for cc in CC:
        g_ = {k_: v for k_, v in sens[cc].items() if not k_.startswith("kr_")}
        for k_, _, tens, _ in SEG:
            g_[f"seg_{k_}"] = sum(sens[cc][f"kr_{t}"] for t in tens)
        grouped[cc] = g_
    for row_ in srows:
        row_.update({f"seg_{k_}_pp_per_100bp": grouped[row_["country"]][f"seg_{k_}"] for k_, _, _, _ in SEG})
    pl.DataFrame(srows).write_csv(OUT / "2026" / "SCENARIO_SENSITIVITY.csv")

    def chart_pies():
        fig, axes = plt.subplots(3, 3, figsize=(11, 10.5))
        for ax, cc in zip(axes.flat, CC):
            keys = [k_ for k_, _, _ in PIE if k_ in grouped[cc]]
            tot = sum(abs(grouped[cc][k_]) for k_ in keys)
            vals = [abs(grouped[cc][k_]) / tot for k_ in keys]
            cols = {k_: c for k_, _, c in PIE}
            wedges, _ = ax.pie(vals, colors=[cols[k_] for k_ in keys], startangle=90, counterclock=False,
                               wedgeprops=dict(width=0.45, edgecolor="white", linewidth=1.5))
            for w_, k_, v in zip(wedges, keys, vals):
                if v >= 0.04:
                    ang = (w_.theta2 + w_.theta1) / 2
                    x, y = 0.78 * math.cos(math.radians(ang)), 0.78 * math.sin(math.radians(ang))
                    dark = k_ in ("sov_growth", "t1_spread", "seg_belly", "seg_long")
                    ax.text(x, y, f"{v*100:.0f}%", ha="center", va="center", fontsize=8, color="white" if dark else INK)
            ax.set_title(f"{NAME[cc]}   (sum of unit sensitivities {tot:.2f} pp)", fontsize=9.5, color=INK)
        handles = [plt.Line2D([], [], marker="s", ls="", color=c, markersize=10, label=lab) for _, lab, c in PIE]
        fig.legend(handles=handles, ncol=4, fontsize=8.5, loc="lower center", bbox_to_anchor=(0.5, 0.0))
        fig.suptitle("Sensitivity of 2036 interest / GDP to a one-unit move in each assumption from the base case: share of the summed absolute sensitivities",
                     x=0.02, ha="left", fontsize=10, color=INK)
        fig.tight_layout(rect=(0, 0.06, 1, 0.96))
        pth = FIG / "pies.png"; fig.savefig(pth, facecolor="white"); plt.close(fig); return pth
    pies_png = chart_pies()

    # ---- bull case: paths and direction of travel -----------------------------------------------------------------
    slope = {c: (val(c, "bull", 2036) - val(c, "bull", 2034)) / 2 for c in CC}
    within3 = {}
    for c in CC:
        inp = inputs26[c]
        bills = sum((b.base_outstanding or 0.0) for b in inp.buckets if not b.in_ladder)
        within3[c] = (sum(inp.ladder[y][0] for y in inp.years[:3]) + bills) / inp.debt0 * 100

    def chart_bull_paths():
        fig, ax = plt.subplots(figsize=(10.5, 5.2))
        yrs = list(range(2026, 2037))
        ends = {}
        for c in CC:
            v = [val(c, "bull", y) for y in yrs]
            col = COL["bull"] if slope[c] < 0 else "#eb6834"
            ax.plot(yrs, v, color=col, lw=2, alpha=0.9)
            ends[c] = v[-1]
        gap = (max(ends.values()) - min(ends.values())) * 0.045          # push labels apart so none overlap
        pos = {}
        for c in sorted(CC, key=lambda c: ends[c]):
            y = ends[c]
            if pos and y - max(pos.values()) < gap:
                y = max(pos.values()) + gap
            pos[c] = y
        for c in CC:
            ax.plot([2036, 2036.4], [ends[c], pos[c]], color=GRAY2, lw=0.6)
            ax.text(2036.5, pos[c], f"{NAME[c]} {ends[c]:.1f} ({slope[c]:+.2f}/yr)", fontsize=7.5, va="center", color=INK)
        ax.axvspan(2026, 2030, color="#f1f0ec", zorder=0); ax.axvspan(2030, 2032, color="#e8e7e3", zorder=0)
        ax.text(2028, ax.get_ylim()[1] * 0.97, "phase 1: boom, market forwards", ha="center", va="top", fontsize=8, color=INK2)
        ax.text(2031, ax.get_ylim()[1] * 0.97, "cuts", ha="center", va="top", fontsize=8, color=INK2)
        ax.text(2034, ax.get_ylim()[1] * 0.97, "phase 2: terminal curve", ha="center", va="top", fontsize=8, color=INK2)
        ax.set_xlim(2026, 2039.5); ax.set_xticks([2026, 2028, 2030, 2032, 2034, 2036]); ax.set_ylabel("interest expense, % of GDP"); ax.grid(axis="x", visible=False)
        ax.plot([], [], color=COL["bull"], lw=2, label="falling by 2036"); ax.plot([], [], color="#eb6834", lw=2, label="still rising in 2036")
        ax.legend(fontsize=8.5, loc="upper left", bbox_to_anchor=(0.0, -0.08), ncol=2)
        ax.set_title("Bull case: interest / GDP (sovereign plus tier 1) through the two phases; label = 2036 level and slope over 2034–36", loc="left", fontsize=10, color=INK)
        pth = FIG / "bull_paths.png"; fig.savefig(pth, facecolor="white"); plt.close(fig); return pth
    bull_png = chart_bull_paths()
    lines.filter(pl.col("year").is_in([2026, 2036])).select("country", "case", "year", "total_pct_gdp", "ngdp_growth_assumed", "g_minus_intgdp", "blended_avg_cost", "r_minus_g").write_csv(OUT / "2026" / "SCENARIO_R_MINUS_G.csv")
    cagr_rows = []
    for cc in CC:
        rec = dict(country=NAME[cc])
        for case in CASES:
            v0, v1 = val(cc, case, 2026), val(cc, case, 2036)
            rec[f"{case}_2026"], rec[f"{case}_2036"] = v0, v1
            rec[f"{case}_cagr"] = ((v1 / v0) ** 0.1 - 1) * 100 if v0 > 0 and v1 > 0 else float("nan")
        cagr_rows.append(rec)
    cagr_df = pl.DataFrame(cagr_rows)
    cagr_df.write_csv(OUT / "2026" / "SCENARIO_CAGR.csv")

    # ---- pdf ------------------------------------------------------------------------------------------------------
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=15, spaceAfter=6, textColor=colors.HexColor(INK))
    P = ParagraphStyle("P", parent=ss["BodyText"], fontSize=9, leading=12.5, spaceAfter=5, textColor=colors.HexColor(INK))
    SM = ParagraphStyle("SM", parent=P, fontSize=7.6, leading=10, textColor=colors.HexColor(INK2))

    def tbl(data, colw, size=7.4):
        t = Table(data, colWidths=colw, repeatRows=1)
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", size), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", size),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(GRAY2)), ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f6f4")])]))
        return t

    def img(p, w, max_h=None):
        im = Image(str(p)); r = im.imageHeight / im.imageWidth
        if max_h and w * r > max_h:
            w = max_h / r
        im.drawWidth, im.drawHeight = w, w * r; return im

    us_rep = ass.filter((pl.col("country") == "US") & (pl.col("case") == "repression")).row(0, named=True)
    W = landscape(A4)[0] - 3.2 * cm
    H = landscape(A4)[1]
    story = [Paragraph("Interest expense / GDP, 2026 against 2036, under four joint cases: all nine countries", H1),
             Paragraph("Each case moves every lever together; the base case is simply market pricing. <b>Bull, an AI boom then disinflation, in two phases.</b> "
                       "Phase 1 (2027–30) is the capex boom: the curve sits on market forwards, nominal growth runs 1 pt above the country's base with inflation still "
                       "3–4%, the revenue harvest takes the primary balance to a surplus by 2030 and tier 1 keeps its middle settings. Phase 2 (2031 on): the buildout is done, disinflation arrives and the central bank "
                       "cuts; the curve glides over 2031–32 to a low terminal level held through 2036 (US 2.0 / 2.2 / 3.0 / 3.5 at 1, 2, 10 and 30 years; France's 10-year "
                       "spread over Bunds tightens to about 100 bp), growth falls back to base for the own-currency inflation targeters (US, UK, Canada, Australia: real +1.5 "
                       "offset by inflation near 1.5) and stays base +1 for the euro members, Denmark and China, whose bases carry little inflation to lose; the budget is the "
                       "best case: the primary balance glides from today's level to a surplus of at least 1% of GDP by 2030 (1.5 pt better for Italy and Denmark, already in "
                       "surplus) and holds it, the revenue harvest that did not materialise after 2001 but is assumed here; tier 1 moves to the tight spread and longer WAM. Who wins depends on maturity structure: short-WAM issuers roll "
                       "into the cuts quickly, long-WAM issuers lock in phase-1 rates for decades (see the direction-of-travel page). <b>Base:</b> base growth, deficit "
                       "held, market forwards, tier 1 at its middle pace. "
                       "<b>Bear, inflation persists and rates stay higher for longer:</b> real −1.5 and inflation +1, so nominal growth 0.5 pt below base; no cuts "
                       "(front end 25 bp over market) and the term premium rebuilds in proportion to the fiscal position (30-year +110 bp for the high-debt countries, "
                       "+65 bp for the low-debt ones, France +50 and Italy +75 bp of spread loaded at ten years and beyond); the deficit worsens 1.5 pt; tier 1 at its "
                       "fastest pace with the shorter WAM and stressed spread. <b>Repression, inflation of 3–4% with the curve engineered down:</b> inflation +1 with "
                       "real growth at base, so nominal growth 1 pt above base; the full cut c is held for the decade (a negative real policy rate) and the long end is "
                       "capped with the term premium near zero, so the curve is flat (ten-year about 1.3 pt over the one-year, thirty-year 0.3 pt over that); the "
                       "deficit is held, because repression substitutes for consolidation and is never paired with an improving budget; tier 1 at its middle pace, "
                       "terming out at the capped rates with spreads compressed to the tight setting as captive banks absorb provinces, states and Länder.", P),
             Paragraph("<b>Two caveats on repression.</b> For Germany, France and Italy it is an ECB-bloc case, not a national choice: it is shown hatched or as a hollow "
                       "diamond, and presenting it next to the US and UK rows without that flag would overstate their options; it is nonetheless Italy's best cell in the "
                       "whole model, which says something about what the euro's survival requires. Australia gets a shallower cap because offshore ownership leaks into "
                       f"the exchange rate. And someone pays: a ten-year yield of about {us_rep['rate_10Y_2028']:.1f}% in the United States against inflation of "
                       "3.5–4% is a negative real return to bondholders for a decade. The interest bill is held flat by transferring the adjustment to savers.", P),
             Paragraph("<b>China</b> is handled on its own terms: growth 6 / 5 / 4 / 5% (bull / base / bear / repression); bull and repression are the yield cap holding "
                       "(market forwards, China already runs the repression curve), base is a developed-market steepening (long end +0.75 to +1 pt) and bear is the cap "
                       "failing, a parallel +1.5 pt shift of the whole curve reached by year two. China's tier 1 includes LGFV bank and trust loans (~RMB 42tn, 29% of "
                       "GDP) which no securities screen captures; every other country is bonds only. Where tier 1 exists the sovereign runs on a central-only deficit so "
                       "sub-national borrowing is not counted twice.", P),
             Paragraph("In each bar chart a pair of bars is one country: the light bar is 2026, the dark bar 2036; the coloured segment is the sovereign and the grey segment "
                       "the fiscal tier-1 blocks. The CAGR above each pair is the compound growth of the total interest/GDP ratio from 2026 to 2036.", P),
             PageBreak()]
    for case in CASES:
        story += [Paragraph(f"{case.capitalize()} case: interest / GDP in 2026 and 2036", H1), img(bar_pngs[case], W, max_h=H - 5.0 * cm), PageBreak()]
    then_png, _, then_now = tvn.build()

    def then_page():
        return [Paragraph(f"Where the interest burden stands today: {tvn.THEN} against {then_now}", H1),
                Paragraph(tvn.CAPTION.format(then=tvn.THEN, now=then_now), P),
                img(then_png, W, max_h=H - 8.0 * cm), Paragraph(tvn.SOURCE.format(then=tvn.THEN, now=then_now), SM)]

    def range_page():
        return [Paragraph("How interest expense over GDP can develop by 2036", H1),
                Paragraph("For each country the dots are interest expense as a share of GDP in 2036 under the four cases, sovereign plus tier 1 (green = bull, blue = base, "
                          "orange = bear, violet = repression; for France, Italy and Germany the repression case is an ECB-bloc decision rather than a national choice). The stacked "
                          "bar beside them shows the nominal GDP growth assumed in each case, % a year, built up from the lowest case: each segment is the extra growth "
                          "that case adds over the one below it, so the top of each segment is that case's growth rate (the bull is its 2027–36 average). Growth and "
                          "interest share the same percentage axis. Countries are grouped by region; Denmark is left out of this chart because its bill is near zero in every case.", P),
                img(range_png, W, max_h=H - 6.0 * cm)]

    def chart_us_compare():
        """United States: every joint case's path, with repression and monetary dominance drawn heavier."""
        fig, ax = plt.subplots(figsize=(10.5, 5.2))
        yrs = list(range(2026, 2037))
        for case in rs.cases_for("US"):
            path = [val("US", case, y) for y in yrs]
            heavy = case in ("repression", "monetary")
            ax.plot(yrs, path, color=COL[case], lw=3.0 if heavy else 1.6, alpha=1.0 if heavy else 0.7, label=SHORT[case])
            ax.text(2036.1, path[-1], f" {path[-1]:.1f}", fontsize=8, va="center", color=INK)
        ax.axvspan(2026, 2030, color="#f1f0ec", zorder=0)
        ax.text(2026.15, ax.get_ylim()[1] * 0.995, "2027–30: Fed tight (monetary dominance) or capped (repression)", ha="left", va="top", fontsize=8, color=INK2)
        ax.set_xlim(2026, 2037); ax.set_xticks([2026, 2028, 2030, 2032, 2034, 2036]); ax.set_ylabel("interest expense, % of GDP"); ax.grid(axis="x", visible=False)
        ax.legend(fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=5)
        ax.set_title("United States: financial repression against monetary dominance (the 1979–98 template), interest / GDP 2026–2036", loc="left", fontsize=10.5, color=INK)
        pth = FIG / "us_compare.png"; fig.savefig(pth, facecolor="white"); plt.close(fig); return pth
    us_png = chart_us_compare()

    def us_page():
        def fmt_growth(r):
            def one(n, re_, inf):
                return f"{n:.1f} ({re_:.1f} {'+' if inf >= 0 else '−'} {abs(inf):.1f})"
            a_ = one(r["nominal_gdp_growth_pct"], r["real_growth_pct"], r["inflation_pct"]); b_ = one(r["nominal_gdp_growth_2036"], r["real_growth_2036"], r["inflation_2036"])
            return a_ if abs(r["nominal_gdp_growth_pct"] - r["nominal_gdp_growth_2036"]) < 0.05 else f"{a_} → {b_}"
        cols = ["bull", "base", "bear", "repression", "monetary"]
        data = [["United States", "2026", "2030", "2036", "Peak", "Avg cost 2030 → 2036", "Debt / GDP 2036", "Growth 2027–36 (real + infl.)", "Primary balance 2030 → 2036"]]
        for case in cols:
            r = ass.filter((pl.col("country") == "US") & (pl.col("case") == case)).row(0, named=True)
            yrs = list(range(2026, 2037)); path = [val("US", case, y) for y in yrs]; pk = max(range(len(yrs)), key=lambda i: path[i])
            data.append([SHORT[case], f"{path[0]:.2f}%", f"{val('US', case, 2030):.2f}%", f"{path[-1]:.2f}%", f"{path[pk]:.2f}% ({yrs[pk]})",
                         f"{val('US', case, 2030, 'sovereign_avg_cost'):.2f} → {val('US', case, 2036, 'sovereign_avg_cost'):.2f}", f"{val('US', case, 2036, 'sovereign_debt_pct_gdp'):.0f}%",
                         fmt_growth(r), f"{r['primary_deficit_2030']:+.1f} → {r['primary_deficit_2036']:+.1f}"])
        return [Paragraph("United States: financial repression against monetary dominance", H1),
                Paragraph("Two ways out of the same arithmetic. <b>Repression</b> caps the front end below inflation for the decade (1-year 1.9%, 2-year 2.2% from 2028) "
                          "while the long end sits at the bear's levels because the Fed cannot hold it, runs inflation a point higher, takes the primary balance to zero by "
                          "2030 and shifts issuance to bills. <b>Monetary dominance</b> is the Volcker template: the Fed holds policy restrictive with a flat curve "
                          "(1-year 5.6%, 10-year 5.6%, 30-year 5.9% from 2028) until inflation is beaten by 2030, a disinflation recession widens the deficit by 1.5 pt of GDP "
                          "first, then credibility lets yields fall to a terminal curve by 2032 (2.5 / 2.7 / 3.5 / 3.9) and the budget is reversed to a 1% surplus by 2036. "
                          "The 1980s version worked from a debt ratio half today's; on twice the stock the same four restrictive years cost far more interest before the "
                          "relief arrives.", P),
                img(us_png, W, max_h=H - 10.5 * cm),
                tbl(data, [3.9 * cm, 1.5 * cm, 1.5 * cm, 1.5 * cm, 2.4 * cm, 3.2 * cm, 2.2 * cm, 5.6 * cm, 3.6 * cm], size=7.4)]

    story += then_page() + [PageBreak()] + range_page() + [PageBreak()] + us_page() + [PageBreak(),
              Paragraph("Nominal growth assumptions, by country", H1),
              Paragraph("Base = average of the 2016–25 CAGR and the latest year; bull = base + 0.5; bear = base − 0.5; repression = base + 1.0 (inflation, not real growth). "
                        "China 6 / 5 / 4 / 5. The hollow circle is the latest observed year (2025). Countries are ordered by the base assumption.", P),
              img(growth_png, W, max_h=H - 6.0 * cm), PageBreak(),
              Paragraph("Nominal growth against interest / GDP", H1),
              Paragraph("Bars: the latest observed nominal GDP growth rate (2025, the same number in every case and year) minus interest expense as a share of GDP "
                        "(sovereign plus fiscal tier 1), in percentage points, so a bar below zero means the interest bill exceeds today's growth rate. Grey is 2026, "
                        "coloured is the case's 2036 interest/GDP. Dots: the outright average interest rate paid on the debt stock, hollow for 2026 and filled for 2036. "
                        "One chart per case follows.", P), PageBreak()]
    for case in CASES:
        story += [img(rg_pngs[case], W, max_h=H - 3.6 * cm), PageBreak()]
    def pies_page(table_note=True):
        return [Paragraph("Which assumptions the ratio is most sensitive to", H1),
                Paragraph("A like-for-like sensitivity rather than a decomposition of the scenarios: each assumption is moved by one unit from the base case with everything "
                          "else at base, and the change in 2036 interest/GDP (sovereign plus tier 1) is recorded as the average of the up and down moves. The units are "
                          "the conventional ones: +1 pp a year of nominal growth, +1 pt of GDP of primary deficit held every year, +100 bp on one segment of the curve at a "
                          "time from 2027 (front end = the 1- to 3-year, belly = 5- and 7-year, long end = 10- to 30-year, each built from bumps at the tenors the sovereign "
                          "issues at that fade linearly to the neighbouring tenors, so tier-1 paper priced at odd maturities moves too; the three segments add up to a "
                          "parallel shift), +1 pp a year of tier-1 stock growth, +1 year of tier-1 WAM, +100 bp of tier-1 spread. Each slice is that lever's share of the "
                          "summed absolute sensitivities, so the picture does not depend on how large the bull and bear settings happen to be. "
                          + ("The table on the next page gives the sensitivities in points of GDP per unit, tenor by tenor, which is what to compare across countries. " if table_note else "")
                          + "A segment's slice is the product of how much the country issues there and how long that paper then sits on the books at the new rate.", P),
                img(pies_png, W, max_h=H - 8.0 * cm)]

    story += pies_page() + [PageBreak(), Paragraph("Sensitivities in points of GDP of 2036 interest / GDP per unit move (base case)", H1)]
    short = {"sov_growth": "Growth +1pp", "sov_deficit": "Deficit +1pt", "t1_growth": "T1 growth +1pp", "t1_wam": "T1 WAM +1y", "t1_spread": "T1 spread +100bp",
             **{f"kr_{t}": f"{t} +100bp" for t in KEYS}}
    sdata = [["Country", "Base 2036"] + [short[k_] for k_, _ in LEVERS] + ["Curve parallel +100bp"]]
    for cc in sorted(CC, key=lambda c: -[r for r in srows if r["country"] == c][0]["base_2036_pct_gdp"]):
        sdata.append([NAME[cc], f"{[r for r in srows if r['country'] == cc][0]['base_2036_pct_gdp']:.2f}%"] + [f"{sens[cc][k_]:+.2f}" if k_ in sens[cc] else "—" for k_, _ in LEVERS]
                     + [f"{parallel[cc]:+.2f}"])
    story += [tbl(sdata, [2.4 * cm, 1.5 * cm] + [1.6 * cm] * len(LEVERS) + [1.9 * cm], size=6.9),
              Paragraph("Negative = the ratio falls when the assumption rises (growth). The eight tenor columns add up to the parallel-shift column (small differences are the "
                        "engine's non-linearity). A tenor's sensitivity is the share of issuance at that tenor times the years that paper then carries the higher coupon "
                        "within the horizon: bills reprice every year, so a 100 bp move in the 1-year rate hits two-thirds of US issuance for a full decade, while a 30-year "
                        "bump only touches the few per cent issued there. Growth matters most where the interest bill is already large (Italy), tier-1 growth and spread "
                        "where the sub-national stock is large (China, Australia, Canada). Tier-1 WAM barely registers because lengthening the book changes when repricing "
                        "happens, not whether.", SM), PageBreak(),
              Paragraph("Interest / GDP in 2026 and 2036 and its 2026–36 CAGR, by case (total including tier 1)", H1)]
    cdata = [["Country"] + [f"{SHORT[c].split(' ')[0]} {k}" for c in CASES for k in ("2026", "2036", "CAGR")]]
    for r in cagr_df.sort("base_2036", descending=True).to_dicts():
        cdata.append([r["country"]] + [f"{r[f'{c}_{k}']:.2f}%" if k != "cagr" else f"{r[f'{c}_cagr']:+.1f}%" for c in CASES for k in ("2026", "2036", "cagr")])
    story += [tbl(cdata, [3.0 * cm] + [1.9 * cm] * 12, size=7.6),
              Paragraph("Repression for Germany, France and Italy is an ECB-bloc case (see the first page).", SM), PageBreak(),
              Paragraph("Bull case: 2036 level and direction of travel", H1),
              Paragraph("The two-phase bull rewards issuers that roll their stock quickly after the 2031–32 cuts and does little for those that locked in phase-1 rates. "
                        "The chart shows the bull path of total interest/GDP for each country; the table gives the level at the end of each phase, the slope over the last "
                        "two years (negative = the ratio is falling by 2036), the sovereign's average cost at the end of phase 1 and in 2036, and the share of today's stock "
                        "that reprices within three years, which is what sets the speed.", P),
              img(bull_png, W, max_h=H - 9.5 * cm)]
    bdata = [["Country", "2026", "2030 (end phase 1)", "2032", "2036", "Slope 2034→36 (pp/yr)", "Avg cost 2030 → 2036", "Reprices within 3y", "Base 2036"]]
    for cc in sorted(CC, key=lambda c: slope[c]):
        bdata.append([NAME[cc], f"{val(cc, 'bull', 2026):.2f}%", f"{val(cc, 'bull', 2030):.2f}%", f"{val(cc, 'bull', 2032):.2f}%", f"{val(cc, 'bull', 2036):.2f}%",
                      f"{slope[cc]:+.2f}", f"{val(cc, 'bull', 2030, 'sovereign_avg_cost'):.2f} → {val(cc, 'bull', 2036, 'sovereign_avg_cost'):.2f}",
                      f"{within3[cc]:.0f}%", f"{val(cc, 'base', 2036):.2f}%"])
    story += [tbl(bdata, [2.6 * cm, 1.7 * cm, 2.6 * cm, 1.7 * cm, 1.7 * cm, 3.0 * cm, 3.2 * cm, 2.6 * cm, 1.9 * cm], size=7.6), PageBreak()]
    BIO = {
        "bull": "AI boom, then disinflation, in two phases. 2027–30: a capex boom financed on market forwards, nominal growth 1 pt above base with inflation still 3–4%, "
                "and a revenue harvest that takes the primary balance to a surplus of at least 1% of GDP by 2030 (1.5 pt better where already in surplus). From 2031 the "
                "buildout is done, inflation falls and central banks cut: the curve glides over 2031–32 to a low terminal level and holds; growth falls back to base for "
                "the US, UK, Canada and Australia and stays base +1 for the euro members, Denmark and China; the surplus is held. Tier 1 keeps its middle growth pace and "
                "moves to the longer WAM and tight spread as the cuts arrive. China's curve stays at market (the cap holds). United States: the boom phase is the same "
                "(real +1.0, inflation unchanged), but from 2031 real growth +1.0 is outweighed by inflation −1.5, so nominal growth runs 0.5 pt below base; the "
                "surplus and the curve path are as above.",
        "base": "Market pricing. New issuance is priced at the forward rates implied by today's curve with today's term premium; nominal growth is the average of the "
                "2016–25 CAGR and the latest year; the primary balance is held at today's level; tier 1 grows at its middle historical pace with its current WAM and "
                "through-cycle spread. China's administered curve steepens the way a developed market's would (long end +0.75 to +1 pt).",
        "bear": "Inflation persists and rates stay higher for longer. No cuts: the front end sits 25 bp over market and the term premium rebuilds in proportion to the "
                "fiscal position (30-year +110 bp for the high-debt countries, +65 bp for the low-debt ones, France +50 and Italy +75 bp of spread from ten years out), "
                "reached by 2028 and held as a spread over market forwards. Nominal growth 0.5 pt below base, the primary deficit 1.5 pt of GDP worse by 2036, tier 1 at "
                "its fastest historical pace with the shorter WAM and stressed spread. China: the yield cap fails, a parallel +1.5 pt shift. United States: real growth "
                "−1.5 with inflation unchanged, so nominal growth is 1.5 pt below base.",
        "monetary": "United States only, the Volcker template of 1979–98. The Fed holds policy restrictive and the curve flat through 2030 (1-year 5.6%, 2-year 5.5%, "
                    "10-year 5.6%, 30-year 5.9% from 2028, kept as a spread over market forwards) until inflation is beaten; the disinflation recession costs 1 pt of real "
                    "growth and the deficit widens 1.5 pt of GDP by 2030 to support the economy. From 2031 the economy recovers (real +0.7) with inflation 1.5 pt lower, "
                    "credibility lets yields fall to a terminal curve by 2032 (2.5 / 2.7 / 3.5 / 3.9, held), and the budget is reversed to a 1% surplus by 2036. Compared "
                    "with the 1980s the starting debt ratio is twice as high, so the four restrictive years cost far more interest before the relief arrives.",
        "repression": "Inflation of 3–4% with the curve engineered down. The full easing cycle is held for the decade (a negative real policy rate) and the long end is "
                      "capped with the term premium near zero, so the curve is flat (10-year about 1.3 pt over the 1-year), reached by 2028 and held as a level. Nominal "
                      "growth 1 pt above base (inflation, not real growth); the primary balance is held, because repression substitutes for consolidation; tier 1 at its "
                      "middle pace with the longer WAM and tight spread as captive banks absorb it. For Germany, France and Italy this is an ECB-bloc case, not a national "
                      "option; Australia gets a shallower cap; China already runs this curve. United States: the Fed holds the front end down (1-year 1.9, 2-year 2.2 in 2028) but cannot hold the long end, which sits where "
                      "the bear puts it (10-year 5.9, 30-year 6.5, kept as a spread over market forwards), so the curve steepens sharply; the primary balance glides to "
                      "zero by 2030 and is held there, and the Treasury leans on the capped front end, with bills rising to 80% of gross issuance from about 65%. Bondholders pay: a 10-year "
                      "near 3.3% against 3.5–4% inflation.",
    }
    SECTOR = {"CA": "provinces", "AU": "states", "CN": "local govt + LGFV", "DE": "Länder", "FR": "CADES, Unédic, ACOSS", "IT": "CDP, FS"}
    H2 = ParagraphStyle("H2", parent=H1, fontSize=12.5, spaceBefore=2, spaceAfter=4)
    PB = ParagraphStyle("PB", parent=P, fontSize=8.6, leading=11.5)
    TC = ParagraphStyle("TC", parent=P, fontSize=7.8, leading=10, spaceAfter=0)

    def arrow(a, b, fmt):
        return fmt.format(a) if abs(a - b) < 0.05 else f"{fmt.format(a)} → {fmt.format(b)}"

    def gsplit(r):
        """'6.3 (3.3 + 3.0)' or, where the path changes, '6.3 (3.3 + 3.0) → 5.3 (3.8 + 1.5)'."""
        def one(n, re_, inf):
            return f"{n:.1f} ({re_:.1f} {'+' if inf >= 0 else '−'} {abs(inf):.1f})"
        a = one(r["nominal_gdp_growth_pct"], r["real_growth_pct"], r["inflation_pct"])
        b = one(r["nominal_gdp_growth_2036"], r["real_growth_2036"], r["inflation_2036"])
        return a if abs(r["nominal_gdp_growth_pct"] - r["nominal_gdp_growth_2036"]) < 0.05 else f"{a} → {b}"

    def assumptions_pages():
        out = [Paragraph("Assumptions behind each case", H1),
               Paragraph("One page per case. Growth is nominal GDP growth, % a year, with its split into real growth and inflation in brackets (an arrow marks a change over "
                         "the horizon). Base real growth is the average of the 2016–25 real GDP CAGR and 2025 (World Bank, constant prices); base inflation is nominal less real, "
                         "i.e. the GDP deflator. The bull adds +1 real with inflation unchanged in the boom, then +1.5 real against −1.5 inflation (US, UK, Canada, Australia) or −0.5 "
                         "(euro members, Denmark); the bear is −1.5 real and +1 inflation; repression is +1 inflation with real growth at base. Primary balance is % of GDP with + = deficit, shown at "
                         "2027, 2030 and 2036; where a country has tier 1 the sovereign runs on the central balance (general government less the sub-national sector's own "
                         "balance) so sub-national borrowing is counted once. The curve is the new-issue rate at 1, 10 and 30 years in 2028 and in 2036; every other tenor "
                         "moves with the nearest set points. Tier 1 is summarised across the fiscal blocks: stock as % of GDP, stock growth in the first year, "
                         "debt-weighted WAM and spread over the sovereign curve (an arrow marks a change over the horizon). * = ECB-bloc case, not a national choice.", P)]
        for case in CASES + ["monetary"]:
            out += ([PageBreak()] if case != CASES[0] else []) + [Paragraph(rs.CASE_LABEL[case], H2), Paragraph(BIO[case], PB)]
            data = [["Country", "Growth, %/yr\nnominal (real + inflation)", "Primary balance, % GDP\n2027 / 2030 / 2036", "Curve 2028\n1Y / 10Y / 30Y", "Curve 2036\n1Y / 10Y / 30Y", "Tier 1 (fiscal blocks)"]]
            for cc in CC:
                if case not in rs.cases_for(cc):
                    continue
                r = ass.filter((pl.col("country") == cc) & (pl.col("case") == case)).row(0, named=True)
                if r["t1_stock_pct_gdp"] > 0:
                    g_s = (f"LGB {r['t1_growth_lgb']:+.0f}%, LGFV {r['t1_growth_lgfv']:+.0f}%" if cc == "CN" else f"{r['t1_growth_yr1']:+.1f}%/yr")
                    t1_s = (f"{SECTOR[cc]}, {r['t1_stock_pct_gdp']:.0f}% of GDP: growth {g_s}; WAM {arrow(r['t1_wam_yr1'], r['t1_wam_2036'], '{:.0f}')}y; "
                            f"spread +{arrow(r['t1_spread_yr1_bp'], r['t1_spread_2036_bp'], '{:.0f}')} bp")
                else:
                    t1_s = "—"
                data.append([NAME[cc] + ("*" if r["bloc_contingent"] else ""),
                             gsplit(r),
                             f"{r['primary_deficit_2027']:+.1f} / {r['primary_deficit_2030']:+.1f} / {r['primary_deficit_2036']:+.1f}",
                             f"{r['rate_1Y_2028']:.1f} / {r['rate_10Y_2028']:.1f} / {r['rate_30Y_2028']:.1f}",
                             f"{r['rate_1Y_2036']:.1f} / {r['rate_10Y_2036']:.1f} / {r['rate_30Y_2036']:.1f}",
                             Paragraph(t1_s, TC)])
            out += [tbl(data, [2.6 * cm, 5.4 * cm, 3.6 * cm, 2.7 * cm, 2.7 * cm, 9.4 * cm], size=7.8)]
        return out


    def sources_pages():
        """Where every input came from, grouped by what it feeds."""
        SH = ParagraphStyle("SH", parent=P, fontSize=9.6, leading=12.5, spaceBefore=5, spaceAfter=1, textColor=colors.HexColor(INK))
        LI = ParagraphStyle("LI", parent=P, fontSize=8.0, leading=10.6, spaceAfter=1.5, leftIndent=10)
        def sec(title, items):
            return [Paragraph(f"<b>{title}</b>", SH)] + [Paragraph("• " + t, LI) for t in items]
        out = [Paragraph("Sources", H1),
               Paragraph("Every number in this deck traces to one of the inputs below. Model code: debt_model.py (cohort roll-forward engine, validated line by line against "
                         "US_Debt_Model_v4.xlsx), build_inputs.py (turns the Bloomberg pulls into the input files), run_scenarios.py (scenario definitions), tier1_overlay.py "
                         "(sub-sovereign blocks), scenario_lines.py and then_vs_now.py (these charts). Snapshot date 16 October 2026 unless stated.", P)]
        out += sec("Debt stock, coupons and maturity ladders (2026 and 2016 vintages)", [
            "Bloomberg SRCH pulls of every live central-government bond and bill per country (data/bloomberg/grid_*.xlsx, not redistributed): amount outstanding, coupon, maturity, type. 2026 pulls "
            "dated 16 Oct 2026; 2016 pulls dated 30 Sep 2016 (US), 31 Mar 2016 (UK, Canada), 30 Jun 2016 (Australia) and end-2016 for the rest. Issue dates are not in the "
            "pull and are estimated from market conventions and the chronological order of CUSIP / SEDOL / ISIN codes, anchored on the 2016 pull.",
            "Issuance composition = lines opened in the last two years by original tenor (Australia: inferred from the maturity profile). Average cost of the stock = "
            "coupon-weighted on coupon debt plus bills at the 1-year rate. US pull excludes TIPS and FRNs; CB holdings ignored."])
        out += sec("Yield curves and term premia", [
            "On-the-run government yields, 16 Oct 2026 (data/bloomberg/grid_xzbzwrw2.xlsx) for the US, Canada, UK, Germany, France and Italy. Short end from public sources, "
            "mid-Oct 2026: policy rates (Fed 3.75–4.00, BoC 2.25, BoE 3.75, ECB deposit 2.50, Danmarks Nationalbank 2.10, RBA 4.60, PBoC 7-day reverse repo 1.40) and "
            "1-year bills (US 1y CMT 16 Oct; Canada 1y bill 14 Oct; UK ~1y gilt 19 Oct; 12m Bubill 12 Oct; 12m BTF 19 Oct; 12m BOT mid-Oct; China 1y CGB 20 Oct).",
            "Curves not in the yields file: China from the ChinaBond CGB curve, 20 Oct 2026; Denmark 2y and 10y quotes of 19 Oct 2026 with 1y, 5y and 30y interpolated; "
            "Australia 3y/5y/10y of 15 Oct 2026, 30y = 10y plus the early-October 30–10 spread, 1y interpolated.",
            "2016 spot curves: user-supplied table (overnight, 2y, 5y, 10y, long bond mapped to 30y; 1y interpolated).",
            "Term premia (5y and 10y, 2016 and 2026): user's OIS decomposition workbook for the US, Canada and UK. Euro members and Denmark built as EUR OIS term premium "
            "plus the Bund swap spread plus the 10-year sovereign spread versus Bunds (Eurostat convergence yields Dec 2016: OAT +50 bp, BTP +164 bp, DGB +14 bp; Oct 2026: "
            "OAT +150.8 bp, BTP +112.4 bp, DGB −17.6 bp). Australia set equal to Canada by instruction. China a judgment estimate anchored on the CGB-versus-policy-rate gap. "
            "(data/bloomberg/country_macro_comparison.xlsx, tabs Country Data, TP Build, Notes & Sources.)"])
        out += sec("Fiscal balances and GDP", [
            "General-government fiscal balances: IMF World Economic Outlook, October 2026 (2026 values are projections; UK 2026 from the April 2026 Fiscal Monitor; US and UK "
            "2016 via FRED). Primary deficit = IMF balance less the model's own interest. Where tier 1 exists the sovereign runs on a central balance = general government "
            "less the tier-1 sector's own 2026 balance (from the tier-1 files).",
            "Nominal GDP, local currency: World Bank WDI, GDP current LCU (NY.GDP.MKTP.CN), 2015, 2016, 2024 and 2025; 2026 extrapolated at the 2025 growth rate. Base "
            "nominal growth = average of the 2016–25 CAGR and 2025."])
        out += sec("Tier-1 (sub-sovereign and quasi-sovereign) debt", [
            "data/tier1/*.csv, built from issuer disclosures 2016–2026: Canadian provincial financing authorities (Ontario, Quebec, Alberta, BC: total debt, budget balance, WAM), "
            "Australian state treasury corporations (NSW TCorp, TCV, QTC, WATC), Chinese Ministry of Finance local-government bond data and LGFV bond buckets by rating, "
            "German Länder debt statistics (securities, Schuldschein and loans), French agencies (CADES, Unédic, ACOSS; SFIL/CAFFIL, Bpifrance, AFL, IDFM as exposure "
            "variants), Italian CDP, FS, regional sinkers and CDP postal savings. Spreads: through-cycle and current (Oct 2026) over the sovereign curve. Method notes in "
            "data/tier1/tier1_model_notes.pdf.",
            "LGFV bank and trust loans (~RMB 42tn) are hardcoded from the notes; no securities screen captures them.",
            "Starting effective interest rates (latest published interest paid / average debt): Ontario 3.3, Quebec 3.7, Alberta 3.1, BC 3.2; NSW 3.7, Victoria 4.6, "
            "Queensland 3.8, WA 3.3; MoF local-government bonds ~3.1; LGFV buckets ~3.6 / 4.3 / 5.2, loans ~4.5; NRW 1.8 and city-states 1.6; CADES 1.9, Unédic 1.4, "
            "ACOSS ~ESTR + 8 bp; SFIL/Bpifrance 2.4; CDP bonds and FS 3.0; CDP postal 2.8 all-in."])
        out += sec("Scenario settings", [
            "Bull terminal curves (2032), bear curves (2028), repression curves (2028), growth and deficit rules and the tier-1 bull / bear settings: specified by the author "
            "of this deck (run_scenarios.py, tier1_overlay.py). China's cases and the ECB-bloc flag for repression likewise."])
        t1src = "; ".join(f"{k.split('_', 1)[1].replace('_', ' ')} {r:.2f}% ({why})" for k, (r, why) in tvn.T1_RATE_2022.items())
        out += sec(f"The {tvn.THEN}-against-{tvn.NOW} chart", [
            tvn.SOURCES["US"], tvn.SOURCES["CA"], tvn.SOURCES["UK"], tvn.SOURCES["FR"], tvn.SOURCES["IT"], tvn.SOURCES["DE"], tvn.SOURCES["DK"], tvn.SOURCES["AU"],
            tvn.SOURCES["CN"], tvn.SOURCES["GDP"],
            f"Tier-1 {tvn.THEN} stocks from the data/tier1 files; {tvn.THEN} effective rates: {t1src}; LGFV loans {tvn.T1_STOCK_2022_OVERRIDE['CN_LGFV_loans']:,.0f} RMB bn (est.).",
            f"{tvn.NOW} is the model's own base-case starting point (SCENARIO_LINES.csv), not an external figure."])
        return out

    story += assumptions_pages()
    story += [PageBreak()] + sources_pages()
    pdf = OUT / "Scenario_Lines.pdf"
    SimpleDocTemplate(str(pdf), pagesize=landscape(A4), leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.3 * cm, bottomMargin=1.3 * cm,
                      title="Interest/GDP scenario lines").build(story)

    # ---- short summary deck: range chart, sensitivity pies, assumptions --------------------------------------------
    summary = then_page() + [PageBreak()] + range_page() + [PageBreak()] + us_page() + [PageBreak()] + pies_page(table_note=False) + [PageBreak()] + assumptions_pages() + [PageBreak()] + sources_pages()
    pdf2 = OUT / "Scenario_Summary.pdf"
    SimpleDocTemplate(str(pdf2), pagesize=landscape(A4), leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.3 * cm, bottomMargin=1.3 * cm,
                      title="Interest/GDP scenario summary").build(summary)
    print("wrote", pdf2)
    with pl.Config(tbl_rows=60, float_precision=2, tbl_hide_dataframe_shape=True, tbl_hide_column_data_types=True, tbl_width_chars=200):
        print(lines.filter(pl.col("year") == 2036).pivot(on="case", index="country", values="total_pct_gdp").select("country", *CASES))
        print(ass.select("country", "case", "nominal_gdp_growth_pct", "primary_deficit_2027", "primary_deficit_2036", "central_primary_deficit_used", "curve",
                         "rate_1Y_2028", "rate_2Y_2028", "rate_10Y_2028", "rate_30Y_2028"))
        print(pl.DataFrame(srows).select("country", "base_2036_pct_gdp", pl.col("^.*_share$").round(2)))
    print("wrote", pdf)


if __name__ == "__main__":
    main()
