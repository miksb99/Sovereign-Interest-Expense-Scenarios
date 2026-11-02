#!/usr/bin/env python3
"""make_tier1_report.py -- PDF on the Tier-1 (sub-sovereign) overlay produced by tier1_overlay.py."""
from __future__ import annotations
from pathlib import Path
import polars as pl
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
import run_scenarios as rs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # repository root (model/ sits one level down)
DATA = ROOT / "data"
OUT = ROOT / "outputs"
D = OUT / "2026"
FIG = OUT / "figures"
FIG.mkdir(parents=True, exist_ok=True)
CC = ["CN", "AU", "CA", "DE", "FR", "IT"]
NAME = {"CA": "Canada", "AU": "Australia", "CN": "China", "DE": "Germany", "FR": "France", "IT": "Italy"}
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
GRAY, GRAY2, INK, INK2, GRID = "#c3c2b7", "#8a8984", "#0b0b0b", "#52514e", "#e8e7e3"
RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
CASE_COL = {"bull": S3, "base": S1, "bear": S2, "repression": "#8e5bd0"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
                     "grid.linewidth": 0.6, "axes.axisbelow": True, "legend.frameon": False, "figure.dpi": 110, "savefig.dpi": 200, "savefig.bbox": "tight"})


def save(fig, name):
    p = FIG / f"{name}.png"; fig.savefig(p, facecolor="white"); plt.close(fig); return p


def chart_stack(cons, path):
    """Sovereign vs tier-1 interest/GDP, 2026 and 2036, consolidated base case."""
    b = cons.filter((pl.col("variant") == "fiscal") & (pl.col("sov_case") == "base") & (pl.col("t1_case") == "base"))
    order = sorted(CC, key=lambda c: b.filter((pl.col("country") == c) & (pl.col("year") == 2036))["total_interest_pct_gdp"][0], reverse=True)
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    w = 0.36
    for j, (yr, alpha) in enumerate(((2026, 0.55), (2036, 1.0))):
        sov = [b.filter((pl.col("country") == c) & (pl.col("year") == yr))["sov_interest_pct_gdp"][0] for c in order]
        t1 = [b.filter((pl.col("country") == c) & (pl.col("year") == yr))["t1_interest_pct_gdp"][0] for c in order]
        xs = [i + (j - 0.5) * w for i in range(len(order))]
        ax.bar(xs, sov, width=w - 0.04, color=RAMP[2], alpha=alpha, label=f"sovereign {yr}", edgecolor="white", linewidth=1.2)
        ax.bar(xs, t1, width=w - 0.04, bottom=sov, color=S2, alpha=alpha, label=f"tier 1 {yr}", edgecolor="white", linewidth=1.2)
        for x, s_, t in zip(xs, sov, t1):
            ax.text(x, s_ + t + 0.08, f"{s_ + t:.1f}", ha="center", fontsize=7.5, color=INK)
    ax.set_xticks(range(len(order)), [NAME[c] for c in order]); ax.set_ylabel("interest expense, % of GDP")
    ax.legend(ncol=4, fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    ax.set_title("Consolidated interest / GDP: sovereign (central deficit) plus fiscal tier-1 blocks, base case", loc="left", fontsize=10, color=INK)
    ax.grid(axis="x", visible=False)
    return save(fig, path)


def chart_paths(cons, path):
    fig, axes = plt.subplots(2, 3, figsize=(7.6, 4.8), sharex=True)
    for ax, cc in zip(axes.flat, CC):
        gg = cons.filter((pl.col("country") == cc) & (pl.col("variant") == "fiscal") & (pl.col("sov_case") == "base") & (pl.col("t1_case") == "base")).sort("year")
        ax.plot(gg["year"], gg["sov_gg_interest_pct_gdp"], color=GRAY2, lw=1.6, ls="--", label="sovereign only (main report)")
        for case in rs.CASES:
            f = cons.filter((pl.col("country") == cc) & (pl.col("variant") == "fiscal") & (pl.col("sov_case") == case) & (pl.col("t1_case") == case)).sort("year")
            ls = "--" if (case == "repression" and cc in rs.BLOC_CONTINGENT) else "-"
            ax.plot(f["year"], f["total_interest_pct_gdp"], color=CASE_COL[case], lw=2, ls=ls, label=f"consolidated {case}")
            ax.text(f["year"][-1], f["total_interest_pct_gdp"][-1], f" {f['total_interest_pct_gdp'][-1]:.1f}", fontsize=7, va="center", color=INK)
        ax.set_title(NAME[cc], loc="left", fontsize=9, color=INK); ax.set_xticks([2026, 2031, 2036])
    axes[0, 0].set_ylabel("% of GDP"); axes[1, 0].set_ylabel("% of GDP")
    h, l = axes[0, 2].get_legend_handles_labels()
    fig.legend(h, l, ncol=5, fontsize=7.5, loc="lower center", bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Interest / GDP: sovereign-only baseline versus the consolidated joint cases (growth, deficit, curve and tier-1 settings moved together; "
                 "dashed violet = repression as an ECB-bloc case)", x=0.01, ha="left", fontsize=9, color=INK)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    return save(fig, path)


def chart_tornado(grid, path):
    """Effect on the 2036 tier-1 add of each lever, bull -> bear, other two at base, market curve, fiscal blocks."""
    g = grid.filter(pl.col("fiscal") & (pl.col("year") == 2036)).group_by("country", "growth_case", "wam_case", "spread_case").agg(pl.col("interest_pct_gdp").sum())
    def val(cc, gc="base", wc="base", sc="base"):
        return g.filter((pl.col("country") == cc) & (pl.col("growth_case") == gc) & (pl.col("wam_case") == wc) & (pl.col("spread_case") == sc))["interest_pct_gdp"][0]
    fig, axes = plt.subplots(2, 3, figsize=(7.6, 4.4))
    for ax, cc in zip(axes.flat, CC):
        base = val(cc)
        rows = [("debt growth", val(cc, gc="bull") - base, val(cc, gc="bear") - base),
                ("WAM", val(cc, wc="bull") - base, val(cc, wc="bear") - base),
                ("spread", val(cc, sc="bull") - base, val(cc, sc="bear") - base)]
        for i, (lab, lo, hi) in enumerate(rows):
            ax.barh(i + 0.17, lo, color=S3, height=0.3); ax.barh(i - 0.17, hi, color=S2, height=0.3)
            ax.text(lo + (0.01 if lo >= 0 else -0.01), i + 0.17, f"{lo:+.2f}", ha="left" if lo >= 0 else "right", va="center", fontsize=6.5, color=INK2)
            ax.text(hi + (0.01 if hi >= 0 else -0.01), i - 0.17, f"{hi:+.2f}", ha="left" if hi >= 0 else "right", va="center", fontsize=6.5, color=INK2)
        ax.axvline(0, color=INK2, lw=0.8); ax.set_yticks(range(3), [r[0] for r in rows])
        span = max(abs(v) for r in rows for v in r[1:]) * 1.9 + 0.1
        ax.set_xlim(-span, span); ax.set_title(f"{NAME[cc]}  (base add {base:.2f}%)", loc="left", fontsize=9, color=INK); ax.grid(axis="y", visible=False)
    fig.suptitle("Which assumption matters: change in the 2036 tier-1 interest add (pp of GDP) from each lever's bull (green) / bear (orange) setting",
                 x=0.01, ha="left", fontsize=9.5, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return save(fig, path)


def build():
    cons = pl.read_csv(D / "CONSOLIDATED_paths.csv")
    grid = pl.read_csv(D / "TIER1_grid.csv")
    ass = pl.read_csv(D / "TIER1_assumptions.csv")
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=16, spaceAfter=8, textColor=colors.HexColor(INK))
    H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12.5, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor(INK))
    P = ParagraphStyle("P", parent=ss["BodyText"], fontSize=9.2, leading=13, spaceAfter=6, textColor=colors.HexColor(INK))
    SM = ParagraphStyle("SM", parent=P, fontSize=8, leading=10.5, textColor=colors.HexColor(INK2))

    def tbl(data, colw=None, size=8):
        t = Table(data, colWidths=colw, repeatRows=1)
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", size), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", size),
                               ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(INK)), ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(GRAY2)),
                               ("LINEBELOW", (0, -1), (-1, -1), 0.3, colors.HexColor(GRAY)), ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f6f4")])]))
        return t

    def img(p, w=17 * cm):
        im = Image(str(p)); r = im.imageHeight / im.imageWidth; im.drawWidth, im.drawHeight = w, w * r; return im

    def c(cc, sov, t1, yr, col="total_interest_pct_gdp", variant="fiscal"):
        return cons.filter((pl.col("country") == cc) & (pl.col("variant") == variant) & (pl.col("sov_case") == sov) & (pl.col("t1_case") == t1) & (pl.col("year") == yr))[col][0]

    story = [Spacer(1, 3 * cm), Paragraph("Tier-1 debt overlay: sub-sovereign and quasi-sovereign borrowing added to the sovereign interest model", H1),
             Paragraph("Canada, Australia, China, Germany, France and Italy. Each block of guaranteed or quasi-fiscal debt is rolled forward on three "
                       "assumptions with bull / base / bear settings (growth of the stock, weighted average maturity, spread to the sovereign curve), "
                       "priced on the same sovereign curves as the main report under its four joint cases (bull, base, bear, repression), and added to the "
                       "sovereign interest bill.", P),
             Paragraph("Contents: 1 Headline · 2 Method and the explicit assumptions · 3 What drives the add · 4 Country notes · 5 Exposure variants and caveats", SM), PageBreak()]

    # ---- 1 headline --------------------------------------------------------------------------------
    story += [Paragraph("1. Headline: how much tier 1 adds", H1), img(chart_stack(cons, "t1_stack"))]
    data = [["Country", "Sov-only 2026", "Tier-1 add 2026", "Consol. 2026", "×", "Sov-only 2036*", "Consol. 2036 base", "Consol. 2036 bull–bear", "Repression 2036", "×", "Tier-1 debt/GDP"]]
    for cc in CC:
        s0, t0, tot0 = c(cc, "base", "base", 2026, "sov_interest_pct_gdp"), c(cc, "base", "base", 2026, "t1_interest_pct_gdp"), c(cc, "base", "base", 2026)
        sgg36, tot36 = c(cc, "base", "base", 2036, "sov_gg_interest_pct_gdp"), c(cc, "base", "base", 2036)
        lo, hi, rep = c(cc, "bull", "bull", 2036), c(cc, "bear", "bear", 2036), c(cc, "repression", "repression", 2036)
        data.append([NAME[cc], f"{s0:.2f}%", f"+{t0:.2f}", f"{tot0:.2f}%", f"{tot0/s0:.1f}", f"{sgg36:.2f}%", f"{tot36:.2f}%", f"{lo:.1f}–{hi:.1f}",
                     f"{rep:.1f}{'†' if cc in rs.BLOC_CONTINGENT else ''}", f"{tot36/sgg36:.1f}", f"{c(cc, 'base', 'base', 2026, 't1_debt_pct_gdp'):.0f}%"])
    story += [tbl(data, colw=[1.7 * cm, 1.7 * cm, 1.7 * cm, 1.7 * cm, 0.7 * cm, 1.8 * cm, 2.0 * cm, 2.1 * cm, 1.7 * cm, 0.7 * cm, 1.6 * cm], size=7.0),
              Paragraph("* Sovereign-only 2036 is the main report's baseline (general-government deficit). Consolidated runs the sovereign on a central-only "
                        "deficit (general government less the tier-1 sector's own balance) so sub-national borrowing is not counted twice, then adds the "
                        "fiscal tier-1 blocks. Bull / base / bear / repression are the joint cases of the main model (growth, deficit, curve and tier-1 settings "
                        "moved together). † = repression is an ECB-bloc case for Germany, France and Italy, not a national option. × = consolidated / sovereign-only. "
                        "France excludes SFIL and Bpifrance; Italy excludes the postal stock (section 5).", SM)]
    cn0, au0, ca0 = c("CN", "base", "base", 2026) / c("CN", "base", "base", 2026, "sov_interest_pct_gdp"), c("AU", "base", "base", 2026) / c("AU", "base", "base", 2026, "sov_interest_pct_gdp"), c("CA", "base", "base", 2026) / c("CA", "base", "base", 2026, "sov_interest_pct_gdp")
    story += [Paragraph(f"<b>Three countries change category.</b> China's interest bill is {cn0:.1f}× the sovereign-only figure once local-government and LGFV bonds are "
                        f"counted ({c('CN','base','base',2026):.1f}% of GDP today, more than Germany's consolidated bill and approaching France's sovereign-only one), "
                        f"Australia's is {au0:.1f}× and Canada's {ca0:.1f}×. Germany adds a third of a point, France a quarter, Italy almost nothing on the fiscal definition.", P),
              Paragraph("<b>The add is persistent, not a one-off level shift.</b> Australia's semis and Canada's provinces grow faster than the federal stock and carry "
                        "longer maturities, so their interest share keeps rising through 2036 even as the sovereign's own path flattens. China's add falls slowly as "
                        "the swap replaces 4–5% LGFV paper with 2% long bonds, which is the one place where consolidation improves the trajectory.", P),
              Paragraph("<b>Multipliers compress over time for China, widen for Australia.</b> The 2036 consolidated-to-sovereign ratio is below today's for China "
                        "because the sovereign's own bill rises while the local one is being refinanced cheaper; for Australia and Canada the ratio stays near 1.7–1.9 "
                        "because provincial and state programmes have no deceleration built in.", P), PageBreak()]

    # ---- 2 method & assumptions --------------------------------------------------------------------------
    story += [Paragraph("2. Method and the explicit assumptions", H1),
              Paragraph("<b>Block model.</b> For each issuer group: stock grows at the assumed rate; one T-th of the stock rolls each year where T ≈ 2 × WAM "
                        "(a uniform ladder); rolled and new debt is priced at the sovereign forward rate for tenor T in that year plus the block's spread; "
                        "retiring debt leaves at the block's average cost; interest = average cost × average stock. Starting average costs are the latest published "
                        "effective interest rates (interest paid / debt), with a vintage-weighted estimate from the 2016 and 2026 curves as a cross-check.", P),
              Paragraph("<b>Growth is calibrated to the stock, not to budget balances</b> (the notes show balances explain less than a third of debt growth), with one "
                        "mechanical rule for every block: three historical windows (the 2016–19 pre-COVID CAGR, the 2021–26 five-year CAGR and last year's growth) ranked so that "
                        "<b>bull is the slowest pace, base the middle one and bear the fastest</b>. China is the exception: its 2016–19 window is dropped because it was "
                        "mostly the reclassification of bank loans into bonds, so bull = last year's pace (6.4%), base = the five-year pace (11.8%) decelerating to 6.4% "
                        "by 2036, bear = 11.8% held. The rule is applied to China's combined local stock while LGFV bonds and loans follow the swap (−3% a year in base "
                        "and bear, −5% bull: the swap is legislated to 2028, so the bear stresses price rather than quantity) and local-government bonds absorb the "
                        "remainder, which keeps swapped debt from being counted twice.", P),
              Paragraph("<b>WAM:</b> base = 2025 debt-weighted; bull = 30% longer (slower repricing); bear = 30% shorter (the ACOSS and putable-postal pathology). "
                        "<b>Spread:</b> base = through-cycle; bull = the tighter of current and through-cycle less 10 bp; bear = the wider of the two plus the stress add "
                        "the notes describe (Canada +25, Australia +30, Germany +15, France and Italy +10, Chinese LGFVs +100 / +150 / +250 by rating bucket).", P),
              Paragraph("<b>Joint cases.</b> The 27-combination grid in section 3 isolates the three tier-1 levers on market forwards. The consolidated paths pair the "
                        "tier-1 settings with the full sovereign case of the same name (growth, deficit path and curve): <b>bull</b> (AI boom then disinflation: "
                        "market forwards, growth +1 and the primary balance gliding to a surplus of at least 1% of GDP by 2030, then the curve glides down over 2031–32 to a low terminal level and growth falls back "
                        "to base for the own-currency countries) with the middle pace throughout and the tight spread and "
                        "longer WAM phased in over 2031–32; <b>bear</b> (inflation "
                        "persists: no cuts, term premium +65 to +110 bp at the long end, growth −0.5, deficit worsens) with the fastest pace, shorter WAM and stressed "
                        "spread; <b>repression</b> (inflation 3–4% with the curve capped: full cut held, 10Y ≈ 1Y + 1.3, growth +1, deficit held) with the middle pace, "
                        "the longer WAM because issuers term out at capped rates, and the tight spread because captive banks absorb provinces, semis and Länder. "
                        "Repression is an ECB-bloc case for Germany, France and Italy. For China bull and repression are the yield cap holding, base a developed-market "
                        "steepening and bear the cap failing (parallel +1.5 pt), so every Chinese block gets dearer in the bear case.", P)]
    data = [["Block", "Stock", "% GDP", "Cost", "WAM b/B/b", "Spread b/B/b (bp)", "Growth b/B/b (%/yr)", "Fiscal"]]
    for blk in ass["block"].unique(maintain_order=True).to_list():
        r = {row["case"]: row for row in ass.filter(pl.col("block") == blk).to_dicts()}
        b = r["base"]
        gfmt = lambda row: (f"{row['growth_yr1']:.0f}→{row['growth_yr10']:.0f}" if abs(row["growth_yr1"] - row["growth_yr10"]) > 0.05 else f"{row['growth_yr1']:.1f}")
        data.append([blk, f"{b['stock_2026']:,.0f}", f"{b['stock_pct_gdp']:.1f}", f"{b['start_cost_pct']:.2f}", f"{r['bull']['wam']:.1f}/{b['wam']:.1f}/{r['bear']['wam']:.1f}",
                     f"{r['bull']['spread_pp']*100:.0f}/{b['spread_pp']*100:.0f}/{r['bear']['spread_pp']*100:.0f}", f"{gfmt(r['bull'])} / {gfmt(b)} / {gfmt(r['bear'])}",
                     "yes" if b["fiscal"] else "exposure"])
    story += [tbl(data, colw=[3.0 * cm, 1.6 * cm, 1.2 * cm, 1.2 * cm, 2.4 * cm, 2.6 * cm, 3.6 * cm, 1.6 * cm], size=7.2),
              Paragraph("Stock in local currency billions at end-2026 (China: billions of yuan). b/B/b = bull / base / bear lever settings. The joint bull case uses the base "
                        "growth with the base WAM and spread through 2030 and the bull WAM and spread from 2032; the repression case uses the base growth with the bull "
                        "WAM and bull spread throughout. Rationale per block is in TIER1_assumptions.csv.", SM),
              Paragraph("<b>Avoiding the double count.</b> The sovereign runs in the main report use IMF general-government deficits, which already include provincial, state, "
                        "Länder and local borrowing. For the consolidated view the sovereign is re-run on a central-only primary deficit: the general-government figure less the "
                        "tier-1 sector's own 2026 balance (Canada −1.2, Australia −0.4, Germany −0.5, China −3.4 points of GDP via special-bond issuance, France and Italy ≈ −0.1). "
                        "This lowers the sovereign-only path for Canada, Australia and China relative to the main report, which is why the consolidated total is less than the "
                        "naive sum of the two.", P), PageBreak()]

    # ---- 3 drivers ----------------------------------------------------------------------------------------
    story += [Paragraph("3. What drives the add", H1), img(chart_tornado(grid, "t1_tornado")),
              Paragraph("Growth of the stock dominates everywhere it is large. The spread lever matters most for China, where the bear case is not a term-premium story but the implicit guarantee being tested "
                        "(LGFV spreads of 300–450 bp in 2018 and 2022); for Canada, Australia and Germany ±20–30 bp on a 15–30% of GDP stock is worth 0.05–0.1 point. "
                        "WAM cuts both ways: a shorter book reprices faster, which is dearer where new money costs more than the stock (Canada, Australia, Germany) "
                        "and cheaper where it costs less (China's swap) or where the curve is steep enough that shorter tenors are simply lower (France).", P),
              img(chart_paths(cons, "t1_paths")),
              Paragraph("The dashed line is the main report's sovereign-only baseline (general-government deficit). The gap between it and the consolidated base line is the "
                        "net effect of adding tier 1 and moving the sovereign to a central deficit. For China the consolidated base runs above the sovereign line throughout; "
                        "for Germany the two nearly touch by 2036 because the Länder stock shrinks relative to GDP while the Bund stock grows.", P), PageBreak()]

    # ---- 4 country notes ----------------------------------------------------------------------------------------
    story += [Paragraph("4. Country notes", H1)]
    notes = {
        "CN": "Local-government bonds (41% of GDP), LGFV bonds (10%) and, unlike every other country here, LGFV bank and trust loans (~RMB 42tn, 29% of GDP, "
              "hardcoded from the notes because no securities screen can see them) are counted. The loans alone add about 1.3 points of GDP of interest today: "
              "RMB 42tn at 4.5% is RMB 1.9tn against GDP of RMB 146tn. The swap replaces 2-year 4–5% chengtou paper with 15-year 2% LGBs, so the local add drifts "
              "down in the base case; the bear case is the yield cap failing (parallel +1.5 pt) plus LGFV spreads back to 2018–22 stress levels.",
        "AU": "The fastest-growing stock in the sample (10% a year since 2016, A$100bn+ gross funding in FY26). Semis sit at the federal WAM, so the overlay inherits federal "
              "repricing speed, and issuance is benchmark-bond-heavy with few bills, so semis feel the bear long end more than the AGS programme does. The add rises from "
              f"{c('AU','base','base',2026,'t1_interest_pct_gdp'):.1f} to {c('AU','base','base',2036,'t1_interest_pct_gdp'):.1f} points of GDP in the base case; Victoria's "
              "A$86bn 2029–34 refinancing wall is the single largest exposure.",
        "CA": "Four provinces carry C$1.0tn against C$1.5tn of federal marketable debt, at an 11-year WAM (federal 5.7) and 70 bp over. Long and expensive, so it reprices "
              "slowly and damps the bear-case front-end benefit: blended, Canada's bill share falls from 49% to roughly a third. The add is about 1.0 point of GDP today and "
              f"{c('CA','base','base',2036,'t1_interest_pct_gdp'):.1f} in 2036; BC's taxpayer-supported debt tripling FY23–29 is the growth risk.",
        "DE": "The only tier-1 stock that shrank 2016–25. The 2025 debt-brake reform gives the Länder 0.35% of GDP of structural room, so forward growth is 2–3% not zero, "
              "but there is no engine comparable to the provinces or semis. The spread (36 bp through-cycle, ~50 now) is a Bund-scarcity artefact rather than credit and is "
              "likely to persist. Add: 0.24 points today, 0.4 by 2036.",
        "FR": "The fiscal blocks (CADES, Unédic, ACOSS, €250bn) add a quarter of a point. The level is small; the structure is the story: CADES amortises €16bn a year on a "
              "legislated schedule while the social-security deficit accumulates in ACOSS bills with no amortisation vehicle, so France's quasi-sovereign WAM is shortening "
              "toward the front of the curve, compounding the 44% bill share flagged in the main report. Spreads move with OATs, not against them.",
        "IT": "On the fiscal definition Italy's tier 1 is negligible (CDP bonds, FS, legacy regional sinkers, €45bn). The €320bn postal stock is the real item and it is a "
              "contingent one: state-guaranteed, putable at par daily, serviced by CDP's asset income, and part of it already sits inside BTP holdings. It appears as an "
              "exposure variant in section 5. Its behaviour in stress (net outflows when BTP yields spike, as in 2022) extends the main report's 'latent-acute' reading.",
    }
    for cc in CC:
        story += [Paragraph(NAME[cc], H2), Paragraph(notes[cc], P)]
    story.append(PageBreak())

    # ---- 5 exposure variants & caveats -------------------------------------------------------------------------
    story += [Paragraph("5. Exposure variants and caveats", H1),
              Paragraph("Adding the non-fiscal blocks (French development banks SFIL/CAFFIL and Bpifrance plus AFL and IDFM, €125bn; Italian postal savings, €322bn) gives the "
                        "guarantee-exposure view. These are serviced by matched assets, so they are a contingent liability rather than a budget cost.", P)]
    data = [["Country", "Fiscal 2026", "Incl. exposure 2026", "Fiscal 2036", "Incl. exposure 2036", "Exposure stock, % GDP"]]
    for cc in ("FR", "IT"):
        data.append([NAME[cc], f"{c(cc,'base','base',2026):.2f}%", f"{c(cc,'base','base',2026, variant='incl_exposure'):.2f}%", f"{c(cc,'base','base',2036):.2f}%",
                     f"{c(cc,'base','base',2036, variant='incl_exposure'):.2f}%", f"{c(cc,'base','base',2026,'t1_debt_pct_gdp','incl_exposure') - c(cc,'base','base',2026,'t1_debt_pct_gdp'):.1f}"])
    story += [tbl(data, colw=[2.4 * cm, 2.2 * cm, 3.0 * cm, 2.2 * cm, 3.0 * cm, 3.2 * cm]), Spacer(1, 0.3 * cm)]
    for t in [
        "<b>Stocks are bonds plus, for Germany, loans and Schuldschein</b> (the Länder securities screen finds ~€450bn of €625bn; interest is paid on all of it) and, for China, "
        "LGFV bank and trust loans (~RMB 42tn, an estimate from the notes rather than a screen). Canada and Australia are treasury-corporation totals including on-lending to state enterprises.",
        "<b>Starting costs</b> are published effective rates and carry ±0.3 points of uncertainty; the vintage-curve cross-check sits 0.3–0.8 points higher for the long-WAM "
        "blocks, which would raise the 2026 add by about a fifth.",
        "<b>The uniform-ladder assumption</b> (one T-th rolls each year) smooths real refinancing walls: Victoria 2029–34, the Chinese LGFV 2027–28 maturities and CADES's 2033 sunset are lumpier than modelled.",
        "<b>Growth rates are the dominant uncertainty</b> and are extrapolations of recent programmes; a 2-point change in Australia's or Canada's growth moves the 2036 add by 0.2–0.3 points of GDP.",
        "<b>The deficit correction</b> uses the sector's 2026 budget balance, which understates its borrowing for Canada and Australia (capital spending is below the line); the sovereign-only "
        "central path is therefore slightly too high rather than too low, and the consolidated total conservative.",
        "<b>Files:</b> data/tier1/*.csv (inputs and notes), model/tier1_overlay.py (model), outputs/2026/TIER1_assumptions.csv, TIER1_blocks.csv, TIER1_grid.csv, CONSOLIDATED_paths.csv.",
    ]:
        story.append(Paragraph(t, P))

    pdf = OUT / "Tier1_Overlay_Report.pdf"
    doc = SimpleDocTemplate(str(pdf), pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm, title="Tier-1 debt overlay")

    def footer(canvas, d):
        canvas.saveState(); canvas.setFont("Helvetica", 7.5); canvas.setFillColor(colors.HexColor(INK2))
        canvas.drawString(1.8 * cm, 1.0 * cm, "Tier-1 debt overlay — six countries, 2026 vintage"); canvas.drawRightString(A4[0] - 1.8 * cm, 1.0 * cm, f"page {d.page}"); canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return pdf


if __name__ == "__main__":
    print("wrote", build())
