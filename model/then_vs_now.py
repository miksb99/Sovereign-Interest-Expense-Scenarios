#!/usr/bin/env python3
"""
then_vs_now.py -- interest / GDP in 2022 against the model's 2026 starting point, sovereign plus tier 1, on the model's own
definitions (marketable central-government securities at their coupon-weighted average cost; tier-1 blocks at their effective
rates).  The average interest rates are kept in the CSV but not drawn.

2026 is EXACTLY the base-case 2026 bar of the scenario charts (SCENARIO_LINES.csv).  2022 is rebuilt from published figures:
  sovereign : end-2022 marketable stock and average coupon / cash cost from each debt office (SOV_2022 below, sources in SOURCES)
  tier 1    : the 2022 stock of each fiscal block from the data/tier1 CSVs (same loader as the overlay) x a 2022 effective rate
              (T1_RATE_2022; published where a figure exists, otherwise an estimate flagged 'est.')
  GDP       : World Bank WDI 2022 nominal GDP, local currency (NY.GDP.MKTP.CN)
Interest = rate x end-year stock, the same convention as the model's base year.

Outputs: outputs/Interest_Then_vs_Now.pdf, outputs/2026/INTEREST_THEN_VS_NOW.csv (incl. sources); build() is imported
by scenario_lines.py for the decks.
"""
from __future__ import annotations
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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Image
import tier1_overlay as t1

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # repository root (model/ sits one level down)
DATA = ROOT / "data"
OUT = ROOT / "outputs"
FIG = OUT / "figures"
FIG.mkdir(parents=True, exist_ok=True)
CC = ["US", "FR", "IT", "UK", "CN", "AU", "CA", "DE", "DK"]
NAME = {"US": "United States", "CA": "Canada", "UK": "United Kingdom", "DE": "Germany", "FR": "France", "IT": "Italy",
        "CN": "China", "DK": "Denmark", "AU": "Australia"}
THEN, NOW = 2022, 2026
S1, INK, INK2, GRID, GRAY = "#2a78d6", "#0b0b0b", "#52514e", "#e8e7e3", "#8a8984"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
                     "grid.linewidth": 0.6, "axes.axisbelow": True, "legend.frameon": False, "figure.dpi": 110, "savefig.dpi": 200, "savefig.bbox": "tight"})

# ---- 2022 sovereign: end-2022 marketable stock (local currency bn), average coupon / cash cost (%), 2022 nominal GDP (bn) -------
SOV_2022 = {
    "US": dict(stock=21394.0, rate=2.32, gdp=26054.6),    # marketable held by the public ex TIPS/FRN (bills 3,696 + notes 13,745 + bonds 3,953), Dec 2022
    "CA": dict(stock=1259.9, rate=2.28, gdp=2864.2),      # market debt and average rate at 31 Mar 2023 (FY2022-23)
    "UK": dict(stock=2378.0, rate=2.00, gdp=2580.9),      # gilts (uplifted nominal) + T-bills at 31 Mar 2023; coupon rate net of RPI uplift (estimate)
    "FR": dict(stock=2278.0, rate=1.49, gdp=2654.0),      # dette negociable Dec 2022; charge de la dette 49.5 less indexation 15.5 = 34.0 over the stock
    "IT": dict(stock=2289.2, rate=2.14, gdp=1998.1),      # titoli di Stato in circolazione end-2022; MEF average cash cost 2022
    "DE": dict(stock=1675.0, rate=1.15, gdp=3989.4),      # Bundeswertpapiere Umlauf 1,877 less own holdings 202; average rate end-2022
    "DK": dict(stock=628.9, rate=1.48, gdp=2831.3),       # domestic debt (bonds + linkers + T-bills) end-2022; interest DKK 9.3bn over the stock
    "AU": dict(stock=895.0, rate=2.09, gdp=2336.9),       # AGS on issue 30 Jun 2022; interest expense A$18.75bn over the stock
    "CN": dict(stock=25869.0, rate=2.52, gdp=123402.9),   # CGB balance end-2022 RMB 25.87tn; interest paid RMB 652bn over the stock
}
SOURCES = {
    "US": "US Treasury, Monthly Statement of the Public Debt and Average Interest Rates on marketable securities, 31 Dec 2022 (total marketable 2.32%)",
    "CA": "Department of Finance Canada, Debt Management Report 2022-23: market debt C$1,259.9bn, average rate 2.28%",
    "UK": "DMO Quarterly Review Jan-Mar 2023 (gilts £2,308bn uplifted nominal + T-bills £70bn); rate = ONS central-government debt interest 2022-23 "
          "(£111.6bn) less the RPI capital uplift on index-linked gilts (~2.6% of GDP, OBR) over the portfolio: estimate, about 2.0%",
    "FR": "AFT, dette negociable de l'Etat fin 2022 €2,278bn; Cour des comptes / Senat, charge de la dette 2022 €49.5bn of which indexation €15.53bn",
    "IT": "MEF, Rapporto sul debito pubblico 2022: titoli di Stato in circolazione €2,289.2bn; costo medio di cassa 2022 2.14%",
    "DE": "Finanzagentur, Kreditaufnahmebericht 2022: Umlaufvolumen €1,877.4bn, Eigenbestand €202.3bn; average interest rate 1.15% at end-2022 (IW Koeln)",
    "DK": "Danmarks Nationalbank, Central government borrowing and debt 2022: domestic debt DKK 628.9bn, interest on domestic debt DKK 9.3bn",
    "AU": "AOFM Annual Report 2021-22: AGS A$895bn at 30 June 2022, interest expense A$18.75bn",
    "CN": "Ministry of Finance, 2022 central final accounts: CGB balance RMB 25,869bn, debt interest expenditure RMB 652.4bn",
    "GDP": "World Bank WDI, GDP current LCU (NY.GDP.MKTP.CN), 2022",
}
# ---- 2022 tier-1 effective rates by block (%), and the one hardcoded stock -----------------------------------------------------
T1_RATE_2022 = {"CA_provinces": (3.3, "est.; Ontario 3.2% effective rate FY2022-23 (OFA)"),
                "AU_semis": (2.2, "est.; NSW TCorp average cost of debt 2.1% at 30 Jun 2022"),
                "CN_LGB": (3.4, "est.; 2022 LGB issuance averaged 3.02% (MoF), older vintages higher"),
                "CN_LGFV_AAA": (4.0, "est."), "CN_LGFV_AAplus": (4.7, "est."), "CN_LGFV_AA_below": (5.6, "est."), "CN_LGFV_loans": (5.0, "est.; LPR-based"),
                "DE_Laender": (1.3, "est.; Bundesbank Laenderfinanzen"),
                "FR_CADES": (1.29, "CADES average financing rate end-2022"), "FR_UNEDIC": (0.49, "Unedic cost of financing 2022"),
                "FR_ACOSS": (0.0, "est.; bill funding at zero / negative rates in 2022"),
                "IT_core": (2.5, "est.")}
T1_STOCK_2022_OVERRIDE = {"CN_LGFV_loans": 38000.0}      # RMB bn, est. (42tn in 2026)
CAPTION = ("Bars: interest expense as a share of GDP in {then} (light) and {now} (dark); the coloured segment is the sovereign, the grey segment the "
           "fiscal tier-1 blocks (provinces, states, local government, Länder, French and Italian agencies). {now} is the model's starting point, "
           "identical to the base-case bars elsewhere in this deck. Countries are ordered by the {now} total.")
SOURCE = ("{then} is rebuilt on the model's definitions from published figures: each sovereign's end-{then} marketable stock and average coupon or cash "
          "cost (US Treasury, Finance Canada, DMO/ONS, AFT and Cour des comptes, MEF, Finanzagentur, Danmarks Nationalbank, AOFM, Chinese MoF), the tier-1 "
          "blocks' {then} stocks from the project's tier-1 files at {then} effective rates (published for Ontario, NSW, CADES and Unédic; estimated for the "
          "rest), and World Bank {then} nominal GDP. The UK rate is coupon interest net of the RPI uplift on index-linked gilts. Full sources per country are "
          "in INTEREST_THEN_VS_NOW.csv.")


def t1_2022(cc: str, gdp: float) -> tuple[float, float, list[str]]:
    """(tier-1 interest % GDP, tier-1 stock, notes) for the fiscal blocks of a country in 2022."""
    interest = stock_tot = 0.0; notes = []
    for b in t1.BLOCKS:
        if b["cc"] != cc or not b["fiscal"]:
            continue
        if b["block"] in T1_STOCK_2022_OVERRIDE:
            stock = T1_STOCK_2022_OVERRIDE[b["block"]]
        else:
            df = pl.read_csv(t1.T1 / b["file"], infer_schema_length=1000)
            ycol = [c for c in df.columns if c.startswith(("fy_end", "cal_year"))][0]
            dcol = [c for c in df.columns if c.startswith("total_debt")][0]
            stock = t1.stock_at(df, b["issuers"], THEN, dcol, ycol, b["unit"])
        rate, why = T1_RATE_2022[b["block"]]
        interest += stock * rate / 100; stock_tot += stock
        notes.append(f"{b['block']}: stock {stock:,.0f} at {rate:.2f}% ({why})")
    return interest / gdp * 100, stock_tot, notes


def build() -> tuple[Path, pl.DataFrame, int]:
    lines = pl.read_csv(OUT / "2026" / "SCENARIO_LINES.csv")
    rows = []
    for cc in CC:
        s = SOV_2022[cc]
        sov_int = s["stock"] * s["rate"] / 100
        t1_pct, t1_stock, notes = t1_2022(cc, s["gdp"])
        now = lines.filter((pl.col("country") == cc) & (pl.col("case") == "base") & (pl.col("year") == NOW)).row(0, named=True)
        rows.append(dict(country=cc, then_year=THEN, now_year=NOW,
                         sov_pct_gdp_then=sov_int / s["gdp"] * 100, t1_pct_gdp_then=t1_pct, total_pct_gdp_then=sov_int / s["gdp"] * 100 + t1_pct,
                         sov_rate_then=s["rate"], blended_rate_then=(sov_int + t1_pct / 100 * s["gdp"]) / (s["stock"] + t1_stock) * 100,
                         sov_stock_then=s["stock"], t1_stock_then=t1_stock, gdp_then=s["gdp"],
                         sov_pct_gdp_now=now["sovereign_pct_gdp"], t1_pct_gdp_now=now["tier1_pct_gdp"], total_pct_gdp_now=now["total_pct_gdp"],
                         sov_rate_now=now["sovereign_avg_cost"], blended_rate_now=now["blended_avg_cost"],
                         source_sovereign=SOURCES[cc], source_tier1="; ".join(notes) if notes else "none", source_gdp=SOURCES["GDP"]))
    df = pl.DataFrame(rows)
    df.write_csv(OUT / "2026" / "INTEREST_THEN_VS_NOW.csv")

    v = {r["country"]: r for r in rows}
    order = sorted(CC, key=lambda c: -v[c]["total_pct_gdp_now"])
    fig, ax = plt.subplots(figsize=(12, 4.8))
    w = 0.38
    handles = []
    for j, (tag, alpha) in enumerate((("then", 0.5), ("now", 1.0))):
        xs = [i + (j - 0.5) * w for i in range(len(order))]
        sov = [v[c][f"sov_pct_gdp_{tag}"] for c in order]; t1v = [v[c][f"t1_pct_gdp_{tag}"] for c in order]
        ax.bar(xs, sov, width=w - 0.04, color=S1, alpha=alpha, edgecolor="white", linewidth=1.2)
        ax.bar(xs, t1v, width=w - 0.04, bottom=sov, color=GRAY, alpha=alpha, edgecolor="white", linewidth=1.2)
        for x, a, b, c in zip(xs, sov, t1v, order):
            top = a + b
            ax.text(x, top + 0.07, f"{top:.1f}", ha="center", fontsize=8, color=INK if tag == "now" else INK2)
        yr = THEN if tag == "then" else NOW
        handles += [Patch(facecolor=S1, alpha=alpha, label=f"sovereign {yr}"), Patch(facecolor=GRAY, alpha=alpha, label=f"tier 1 {yr}")]
    top = max(max(v[c]["total_pct_gdp_now"], v[c]["total_pct_gdp_then"]) for c in CC)
    ax.set_ylim(0, top * 1.15)
    ax.set_xticks(range(len(order)), [NAME[c] for c in order], fontsize=9)
    ax.set_ylabel("interest expense, % of GDP"); ax.grid(axis="x", visible=False)
    ax.legend(handles=handles, ncol=4, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    ax.set_title(f"Interest / GDP in {THEN} (light) and {NOW} (dark), sovereign plus tier 1 (grey)",
                 loc="left", fontsize=10, color=INK)
    png = FIG / "then_vs_now.png"; fig.savefig(png, facecolor="white"); plt.close(fig)
    return png, df, NOW


def main() -> None:
    png, df, now = build()
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=15, spaceAfter=6, textColor=colors.HexColor(INK))
    P = ParagraphStyle("P", parent=ss["BodyText"], fontSize=9, leading=12.5, spaceAfter=5, textColor=colors.HexColor(INK))
    SM = ParagraphStyle("SM", parent=P, fontSize=7.8, leading=10.5, textColor=colors.HexColor(INK2))
    W, Hp = landscape(A4)[0] - 3.2 * cm, landscape(A4)[1]
    im = Image(str(png)); r_ = im.imageHeight / im.imageWidth
    wdt = min(W, (Hp - 8.5 * cm) / r_); im.drawWidth, im.drawHeight = wdt, wdt * r_
    story = [Paragraph(f"Interest burden then and now: {THEN} against {now}", H1), Paragraph(CAPTION.format(then=THEN, now=now), P), im,
             Paragraph(SOURCE.format(then=THEN, now=now), SM)]
    pdf = OUT / "Interest_Then_vs_Now.pdf"
    SimpleDocTemplate(str(pdf), pagesize=landscape(A4), leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.3 * cm, bottomMargin=1.3 * cm,
                      title="Interest burden then and now").build(story)
    with pl.Config(float_precision=2, tbl_hide_dataframe_shape=True, tbl_hide_column_data_types=True, tbl_width_chars=220):
        print(df.select("country", "sov_pct_gdp_then", "t1_pct_gdp_then", "total_pct_gdp_then", "blended_rate_then", "sov_pct_gdp_now", "t1_pct_gdp_now", "total_pct_gdp_now", "blended_rate_now"))
    print("wrote", pdf)


if __name__ == "__main__":
    main()
