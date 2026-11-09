#!/usr/bin/env python3
"""
build_inputs.py -- turn the Bloomberg SRCH pulls in data/bloomberg/ into one debt_model input CSV per country (data/inputs/).

Steps per country
  1. load the 2026 bond pull (and the 2016 one for history), clean, dedupe, keep domestic issues
  2. bills  -> base-year stock (Bills bucket, not in ladder)
     coupons (fixed, floating, step, linkers) -> maturity ladder by calendar year
  3. average cost of the stock = amount-weighted coupon (linkers: real coupon + INFLATION_ACCRUAL),
     bills at the 1Y spot yield
  4. issuance composition: no issue dates in the pull, so inferred from the maturity profile under a
     steady-state assumption (annual issuance at tenor m = maturing in year m minus maturing in year m+1,
     after a monotone smoothing of the profile); bills issuance = bills stock (one-pass convention)
  5. curves: on-the-run yields file + policy rate / 1Y points from MARKET below; term premia from the
     macro workbook, shaped across tenors with the US ACM-style profile
  6. macro: GDP levels/growth, IMF general-government balance -> primary deficit = -balance - cost0*debt0/GDP
"""
from __future__ import annotations
import glob, re, sys
from datetime import date, datetime
from pathlib import Path
import polars as pl
import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # repository root (model/ sits one level down)
DATA = ROOT / "data"
BBG = DATA / "bloomberg"               # raw Bloomberg SRCH pulls (licensed; not in the repository)
OUT = DATA / "inputs"
SNAPSHOT = date(2026, 10, 16)     # set per (country, vintage) inside build_all
BASE_YEAR = 2026                  # idem
VINTAGES = (2026, 2016)
INFLATION_ACCRUAL = 2.0          # pp added to linkers' real coupons to approximate inflation uplift

# ---------------------------------------------------------------- country definitions
C = {
    "US": dict(name="United States", ccy="USD", macro="United States", tickers={"T", "B"}, bills={"B"},
               mkt={"US GOVERNMENT"}, frn_mat=2),
    "CA": dict(name="Canada", ccy="CAD", macro="Canada", tickers={"CAN", "CTB"}, bills={"CTB"},
               mkt={"CANADIAN"}, frn_mat=2),
    "UK": dict(name="United Kingdom", ccy="GBP", macro="United Kingdom", tickers={"UKT", "UKTI", "UKTB"},
               bills={"UKTB"}, mkt={"UK GILT STOCK", "DOMESTIC"}, frn_mat=2),
    "DE": dict(name="Germany", ccy="EUR", macro="Germany", tickers={"DBR", "OBL", "BKO", "BUBILL"},
               bills={"BUBILL"}, mkt={"EURO-ZONE"}, frn_mat=2),
    "FR": dict(name="France", ccy="EUR", macro="France", tickers={"FRTR", "BTF"}, bills={"BTF"},
               mkt={"EURO-ZONE"}, frn_mat=2),
    "IT": dict(name="Italy", ccy="EUR", macro="Italy", tickers={"BTPS", "CCTS", "BOTS"}, bills={"BOTS"},
               mkt={"EURO-ZONE"}, frn_mat=7),
    "CN": dict(name="China", ccy="CNY", macro="China", tickers={"CGB"}, bills=set(),
               mkt={"DOMESTIC"}, frn_mat=2),
    "DK": dict(name="Denmark", ccy="DKK", macro="Denmark", tickers={"DGB", "DGTB"}, bills={"DGTB"},
               mkt={"DOMESTIC"}, frn_mat=2),
    "AU": dict(name="Australia", ccy="AUD", macro="Australia", tickers={"ACGB", "ACTB"}, bills={"ACTB"},
               mkt={"AUSTRALIAN"}, frn_mat=2),
}
# on-the-run yields file maps tickers -> country
YIELD_TICKER = {"UKT": "UK", "T": "US", "BKO": "DE", "OBL": "DE", "DBR": "DE", "FRTR": "FR", "CAN": "CA", "BTPS": "IT"}

# short end and missing curves, filled from public sources (see notes written into each CSV)
# Short-end points and the three curves missing from the yields file.  Public sources, mid-Oct 2026:
#   policy rates: Fed 3.75-4.00 (mid 3.88), BoC 2.25, BoE 3.75, ECB deposit 2.50, DN 2.10, RBA 4.60, PBoC 7d RR 1.40
#   1Y: US 1y CMT 4.46 (16-Oct), CA 1y bill 2.93 (14-Oct), UK ~1y gilt 4.50 (19-Oct), DE 12m Bubill 2.95 (12-Oct),
#       FR 12m BTF 3.29 (19-Oct), IT 12m BOT 3.18 (mid-Oct), CN 1y CGB 1.18 (20-Oct)
#   AU 1Y and DK 1Y/5Y/30Y are interpolated/extrapolated (flagged in the CSV notes)
MARKET: dict[str, dict] = {
    "US": {"O/N": 3.88, "1Y": 4.46},
    "CA": {"O/N": 2.25, "1Y": 2.93},
    "UK": {"O/N": 3.75, "1Y": 4.50},
    "DE": {"O/N": 2.50, "1Y": 2.95},
    "FR": {"O/N": 2.50, "1Y": 3.29},
    "IT": {"O/N": 2.50, "1Y": 3.18},
    "CN": {"O/N": 1.40, "1Y": 1.18, "2Y": 1.24, "5Y": 1.35, "10Y": 1.64, "30Y": 2.05},       # ChinaBond curve 20-Oct
    "DK": {"O/N": 2.10, "1Y": 2.45, "2Y": 2.83, "5Y": 3.05, "10Y": 3.29, "30Y": 3.65},       # 2Y/10Y 19-Oct; 1Y,5Y,30Y interpolated
    "AU": {"O/N": 4.60, "1Y": 4.65, "3Y": 4.83, "5Y": 4.88, "10Y": 5.21, "30Y": 5.66},       # 15-Oct; 1Y interpolated, 30Y = 10Y + early-Oct 30-10 spread
}
# Real GDP growth, % (World Bank WDI, constant LCU, NY.GDP.MKTP.KN; retrieved 9 Nov 2026): (2025 y/y, 2016-2025 CAGR).
# Written to the 2026 inputs so run_scenarios.py can split nominal growth into real growth + inflation (presentation only).
REAL_GROWTH_2026 = {
    "AU": (1.3504, 2.1922),
    "CA": (1.7427, 2.0736),
    "CN": (4.9599, 5.4394),
    "DE": (0.2396, 0.5727),
    "DK": (2.9284, 2.0658),
    "FR": (0.8409, 1.2023),
    "IT": (0.5396, 1.0113),
    "UK": (1.3884, 1.2433),
    "US": (2.1614, 2.4800),
}
MARKET_NOTE = {
    "US": "O/N = fed funds mid 3.75-4.00; 1Y = 1y CMT 16-Oct-2026; rest = on-the-run yields file",
    "CA": "O/N = BoC 2.25; 1Y = 1y T-bill 14-Oct-2026; rest = on-the-run yields file",
    "UK": "O/N = Bank Rate 3.75; 1Y = ~1y gilt 19-Oct-2026; rest = on-the-run yields file",
    "DE": "O/N = ECB deposit 2.50; 1Y = 12m Bubill auction 12-Oct-2026; rest = on-the-run yields file",
    "FR": "O/N = ECB deposit 2.50; 1Y = 12m BTF auction 19-Oct-2026; rest = on-the-run yields file",
    "IT": "O/N = ECB deposit 2.50; 1Y = 12m BOT auction mid-Oct-2026; rest = on-the-run yields file",
    "CN": "NOT in yields file: ChinaBond CGB curve 20-Oct-2026; O/N = PBoC 7d reverse repo 1.40",
    "DK": "NOT in yields file: 2Y 2.83 and 10Y 3.29 from 19-Oct-2026 quotes; 1Y, 5Y, 30Y INTERPOLATED; O/N = DN CD rate 2.10",
    "AU": "NOT in yields file: 3Y/5Y/10Y 15-Oct-2026; 30Y = 10Y + 0.45 (early-Oct 30-10 spread); 1Y INTERPOLATED; O/N = RBA cash 4.60",
}
# 2016 spot rates supplied by the user (Overnight, 2Y, 5Y, 10Y, long bond).  1Y = midpoint of O/N and 2Y;
# the long bond is mapped to the 30Y point.  Each country's 2016 pull date is its snapshot.
MARKET_2016 = {
    "US": {"O/N": 0.66, "2Y": 1.29, "5Y": 2.10, "10Y": 2.60, "30Y": 3.16},
    "CA": {"O/N": 0.50, "2Y": 0.85, "5Y": 1.24, "10Y": 1.85, "30Y": 2.42},
    "UK": {"O/N": 0.25, "2Y": 0.12, "5Y": 0.60, "10Y": 1.47, "30Y": 2.10},
    "FR": {"O/N": -0.35, "2Y": -0.65, "5Y": -0.08, "10Y": 0.82, "30Y": 1.85},
    "DE": {"O/N": -0.35, "2Y": -0.78, "5Y": -0.45, "10Y": 0.36, "30Y": 1.14},
    "IT": {"O/N": -0.35, "2Y": -0.08, "5Y": 1.00, "10Y": 1.90, "30Y": 3.10},
    "DK": {"O/N": -0.65, "2Y": -0.60, "5Y": -0.27, "10Y": 0.50, "30Y": 0.95},
    "AU": {"O/N": 1.50, "2Y": 1.85, "5Y": 2.35, "10Y": 2.86, "30Y": 3.50},
    "CN": {"O/N": 2.30, "2Y": 2.80, "5Y": 3.05, "10Y": 3.30, "30Y": 3.75},
}
for _cc, _m in MARKET_2016.items():
    _m["1Y"] = round((_m["O/N"] + _m["2Y"]) / 2, 3)
MARKET_NOTE_2016 = "user-supplied 2016 spot table (O/N, 2Y, 5Y, 10Y, long bond=30Y); 1Y interpolated between O/N and 2Y"
# term premia 2026 (bps) from country_macro_comparison: 5Y, 10Y; shaped across tenors with the US ACM-style
# profile (1Y/2Y/3Y = 0.156/0.3125/0.5625 x TP5, 7Y linear between, 20Y/30Y = 1.377/1.449 x TP10).  CN = 0 per user.
TP_SHAPE_SHORT = {"1Y": 0.05 / 0.32, "2Y": 0.10 / 0.32, "3Y": 0.18 / 0.32}
TP_SHAPE_LONG = {"20Y": 0.95 / 0.69, "30Y": 1.0 / 0.69}
MIX_METHOD = "ma3"   # ladder-profile variant used as fallback: "raw" | "ma3" | "iso"  (see aggregate())
MIX_SOURCE = {2026: {cc: "dated" for cc in ["US", "CA", "UK", "DE", "FR", "IT", "CN", "DK"]} | {"AU": "ladder"},
              2016: {"US": "dated", "CA": "dated", "DE": "dated"}}   # 2016: no earlier pull to anchor identifiers

# ---------------------------------------------------------------- helpers
def read_pull(path: Path):
    wb = openpyxl.load_workbook(path, data_only=True)
    if "Bonds" not in wb.sheetnames:
        return None
    ctx = " ".join(str(v) for row in wb["Context"].iter_rows(values_only=True) for v in row if v)
    asof = datetime.strptime(ctx.split("SRCH as of date:")[1].split()[0], "%m/%d/%Y").date()
    rows = list(wb["Bonds"].iter_rows(values_only=True))
    hdr = [str(h) for h in rows[0]]
    df = pl.DataFrame({h: [r[i] for r in rows[1:]] for i, h in enumerate(hdr)}, strict=False)
    return asof, df


def clean(df: pl.DataFrame, cfg: dict, asof: date) -> pl.DataFrame:
    """Numeric amounts, parsed maturity, domestic only, live only, deduped."""
    d = (df.with_columns(
            pl.col("Amt Out").cast(pl.Float64, strict=False).alias("amt"),
            pl.col("Coupon").cast(pl.Float64, strict=False).fill_null(0.0).alias("cpn"),
            pl.col("Maturity").cast(pl.Utf8).str.strptime(pl.Date, "%m/%d/%Y", strict=False).alias("mat"),
            pl.col("Inflation-linked").cast(pl.Utf8).str.to_lowercase().eq("true").alias("linker"),
            pl.col("Coupon Type").cast(pl.Utf8).str.to_uppercase().alias("ctype"),
            pl.col("Ticker").cast(pl.Utf8).alias("tic"),
            pl.col("Market Type").cast(pl.Utf8).alias("mkt"),
            pl.col("ISIN").cast(pl.Utf8).alias("isin"))
         .filter(pl.col("amt") > 0)
         .filter(pl.col("mat").is_not_null() & (pl.col("mat") > pl.lit(asof)))
         .filter(pl.col("mkt").is_in(list(cfg["mkt"])))
         .filter(~pl.col("ctype").str.contains("WHEN ISSUED"))
         .unique(subset=["isin"], keep="first", maintain_order=True))
    d = d.with_columns(
        (pl.col("tic").is_in(list(cfg["bills"])) | pl.col("ctype").str.starts_with("ZERO") & (pl.col("mat") <= pl.lit(date(asof.year + 1, asof.month, asof.day)))).alias("is_bill"),
        pl.col("ctype").str.contains("FLOAT").alias("is_frn"),
        (pl.col("cpn") + pl.when(pl.col("linker")).then(INFLATION_ACCRUAL).otherwise(0.0)).alias("cpn_eff"),
        ((pl.col("mat") - pl.lit(asof)).dt.total_days() / 365.25).alias("yrs"),
    )
    return d


def isotonic_decreasing(v: list[float]) -> list[float]:
    """Pool-adjacent-violators: closest non-increasing sequence to v (least squares)."""
    blocks = [[x, 1] for x in v]            # [mean, count]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] < blocks[i + 1][0]:
            m = (blocks[i][0] * blocks[i][1] + blocks[i + 1][0] * blocks[i + 1][1]) / (blocks[i][1] + blocks[i + 1][1])
            blocks[i] = [m, blocks[i][1] + blocks[i + 1][1]]
            del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    out = []
    for m, n in blocks:
        out += [m] * n
    return out


BUCKETS = ["Bills", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y", "FRN"]
BUCKET_MAT = {"Bills": 1, "2Y": 2, "3Y": 3, "5Y": 5, "7Y": 7, "10Y": 10, "20Y": 20, "30Y": 30}
BUCKET_TENOR = {"Bills": "1Y", "2Y": "2Y", "3Y": "3Y", "5Y": "5Y", "7Y": "7Y", "10Y": "10Y", "20Y": "20Y", "30Y": "30Y", "FRN": "O/N"}


def bucket_of(k: int) -> str:
    return ("Bills" if k <= 1 else "2Y" if k <= 2 else "3Y" if k <= 4 else "5Y" if k <= 6 else
            "7Y" if k <= 8 else "10Y" if k <= 14 else "20Y" if k <= 24 else "30Y")


def aggregate(d: pl.DataFrame, cfg: dict, base_year: int) -> dict:
    bills = d.filter(pl.col("is_bill"))
    cpns = d.filter(~pl.col("is_bill"))
    frn = cpns.filter(pl.col("is_frn"))
    # ladder by calendar year; maturities before the first full year fold into year 1
    lad = (cpns.with_columns(pl.max_horizontal(pl.col("mat").dt.year(), pl.lit(base_year + 1)).alias("y"))
           .group_by("y").agg(pl.col("amt").sum().alias("amt"),
                              (pl.col("amt") * pl.col("cpn_eff")).sum().alias("wc"))
           .with_columns((pl.col("wc") / pl.col("amt")).alias("cpn")).sort("y"))
    ladder = {int(y): (a / 1e9, c) for y, a, c in lad.select("y", "amt", "cpn").iter_rows()}
    # steady-state issuance inference on rolling 12-month windows from the snapshot date:
    # N_k = coupon debt maturing in the k-th year ahead; annual issuance at tenor k ~ N_k - N_{k+1}
    # (negative differences from lumpiness are clipped; no further smoothing -- tested on the US,
    # where this reproduces the known tenor split well, while monotone smoothing understates 10y)
    K = int(cpns["yrs"].max()) + 1
    win = cpns.with_columns(pl.col("yrs").ceil().cast(pl.Int64).alias("k")).group_by("k").agg(pl.col("amt").sum() / 1e9)
    N = {int(k): a for k, a in win.iter_rows()}
    Nk = [N.get(k, 0.0) for k in range(1, K + 2)]
    if MIX_METHOD == "ma3":        # 3-year centred moving average kills single-bond lumps, keeps cliffs
        Nk = [Nk[0]] + [(Nk[i - 1] + Nk[i] + Nk[i + 1]) / 3 for i in range(1, K)] + [Nk[K]]
    elif MIX_METHOD == "iso":
        Nk = isotonic_decreasing(Nk[:K]) + [0.0]
    I = {k: max(Nk[k - 1] - Nk[k], 0.0) for k in range(1, K + 1)}
    mix = {b: 0.0 for b in BUCKETS}
    for k, v in I.items():
        # k = 1 is non-stationarity noise where bills are pulled separately -> shortest coupon bucket;
        # where bills are not separately identified (China) it is genuine sub-1y issuance
        mix["2Y" if (k == 1 and cfg["bills"]) else bucket_of(k)] += v
    mix["FRN"] = frn["amt"].sum() / 1e9 / cfg["frn_mat"]
    mix["Bills"] += bills["amt"].sum() / 1e9          # one-pass: bills issued per year ~ bills stock
    tot = sum(mix.values())
    mix = {b: round(v / tot, 6) for b, v in mix.items()}
    big = max(mix, key=mix.get)
    mix[big] = round(mix[big] + (1.0 - sum(mix.values())), 6)      # rounding residual -> largest bucket
    return dict(
        bills_out=bills["amt"].sum() / 1e9, coupon_out=cpns["amt"].sum() / 1e9, frn_out=frn["amt"].sum() / 1e9,
        linker_out=cpns.filter(pl.col("linker"))["amt"].sum() / 1e9,
        coupon_wavg=(cpns["amt"] * cpns["cpn_eff"]).sum() / cpns["amt"].sum(),
        n_bonds=cpns.height, n_bills=bills.height, ladder=ladder, mix=mix, coupon_issuance=sum(I.values()),
    )


def load_all():
    pulls = {}
    for f in sorted(glob.glob(str(BBG / "grid_*.xlsx"))):
        r = read_pull(Path(f))
        if r is None:
            continue
        asof, df = r
        tick = set(df["Ticker"].cast(pl.Utf8).unique().to_list())
        cc = next(c for c, cfg in C.items() if tick <= cfg["tickers"])
        pulls[(cc, asof.year)] = (asof, clean(df, C[cc], asof), Path(f).name)
    return pulls


if __name__ == "__main__" and "--diagnose" in sys.argv:
    pulls = load_all()
    for cc in C:
        asof, d, fn = pulls[(cc, 2026)]
        a = aggregate(d, C[cc], BASE_YEAR)
        print(f"\n{cc} ({fn}, as of {asof}): bonds={a['n_bonds']} bills={a['n_bills']}  "
              f"total={a['bills_out']+a['coupon_out']:,.0f}bn  bills={a['bills_out']:,.0f}  coupons={a['coupon_out']:,.0f}  "
              f"linkers={a['linker_out']:,.0f}  FRN={a['frn_out']:,.0f}  coupon wavg={a['coupon_wavg']:.2f}%")
        print("   ladder:", {y: (round(v[0]), round(v[1], 2)) for y, v in list(a['ladder'].items())[:12]})
        print("   inferred mix:", {b: round(s, 3) for b, s in a['mix'].items()}, f" coupon issuance/yr={a['coupon_issuance']:,.0f}")
        if (cc, 2016) in pulls:
            asof16, d16, _ = pulls[(cc, 2016)]
            a16 = aggregate(d16, C[cc], asof16.year)
            print(f"   2016 ({asof16}): total={a16['bills_out']+a16['coupon_out']:,.0f}bn  coupon wavg={a16['coupon_wavg']:.2f}%")


# =============================================================================================
#  curves, macro, and the CSV writer
# =============================================================================================
def read_yields() -> dict[str, list[tuple[float, float]]]:
    """On-the-run yields file -> {cc: [(years_to_maturity, yield), ...]}."""
    wb = openpyxl.load_workbook(BBG / "grid_xzbzwrw2.xlsx", data_only=True)
    out: dict[str, list[tuple[float, float]]] = {}
    for sec_id, sec, dur, px, yld, *_ in wb.worksheets[0].iter_rows(values_only=True):
        if not isinstance(yld, (int, float)) or not isinstance(sec, str):
            continue
        tic, mat = sec.split()[0], sec.split()[-1]
        m, d, y = mat.split("/")
        y = int(y) + (2000 if len(y) == 2 else 0)
        yrs = (date(y, int(m), int(d)) - SNAPSHOT).days / 365.25
        out.setdefault(YIELD_TICKER[tic], []).append((round(yrs, 1), float(yld)))
    return out


def read_macro() -> dict[str, dict]:
    wb = openpyxl.load_workbook(BBG / "country_macro_comparison (2).xlsx", data_only=True)
    cd = {r[0]: r for r in wb["Country Data"].iter_rows(values_only=True) if r[1] in ("USD", "CAD", "GBP", "EUR", "DKK", "AUD", "CNY")}
    gl = {r[0]: r for r in wb["GDP Levels"].iter_rows(values_only=True) if isinstance(r[1], (int, float))}
    # European premia in the macro sheet = EUR OIS TP + Bund swap spread + sovereign spread vs Bund (TP Build tab).
    # The sovereign spread is a flat credit/liquidity premium across tenors, so it must not be shaped with maturity.
    build = {}
    for r in wb["TP Build"].iter_rows(values_only=True):
        if r[0] in ("Germany", "France", "Italy", "Denmark") and r[1] in ("5Y", "10Y"):
            build[(r[0], r[1])] = dict(core16=(r[2] + r[3]) / 100, sprd16=r[4] / 100, core26=(r[6] + r[7]) / 100, sprd26=r[8] / 100)
    out = {}
    for cc, cfg in C.items():
        r, g = cd[cfg["macro"]], gl[cfg["macro"]]
        d = dict(bal16=r[2], bal26=r[3], g16=r[5] * 100, g25=r[6] * 100,
                 tp5_16=r[8] / 100, tp10_16=r[9] / 100, tp5=r[10] / 100, tp10=r[11] / 100, tp_note=r[12],
                 gdp15=g[1], gdp16=g[2], gdp24=g[3], gdp25=g[4], sprd=0.0, sprd16=0.0)
        if (cfg["macro"], "5Y") in build:
            b5, b10 = build[(cfg["macro"], "5Y")], build[(cfg["macro"], "10Y")]
            d.update(tp5=b5["core26"], tp10=b10["core26"], sprd=b5["sprd26"], tp5_16=b5["core16"], tp10_16=b10["core16"], sprd16=b5["sprd16"])
        out[cc] = d
    return out


def tp_curve(tp5: float, tp10: float, sprd: float = 0.0) -> dict[str, float]:
    """Core (rate) term premium shaped across tenors + a flat sovereign spread on every tenor from 1Y out."""
    core = {"1Y": TP_SHAPE_SHORT["1Y"] * tp5, "2Y": TP_SHAPE_SHORT["2Y"] * tp5, "3Y": TP_SHAPE_SHORT["3Y"] * tp5,
            "5Y": tp5, "7Y": tp5 + (tp10 - tp5) * 2 / 5, "10Y": tp10,
            "20Y": TP_SHAPE_LONG["20Y"] * tp10, "30Y": TP_SHAPE_LONG["30Y"] * tp10}
    return {"O/N": 0.0, **{k: v + sprd for k, v in core.items()}}


def q(s: str) -> str:
    """CSV-quote a note."""
    return '"' + str(s).replace('"', "'") + '"'


def write_csv(cc: str, vintage: int, a: dict, hist: dict, asof: date, curve: dict[str, float], m: dict,
              fn: str, curve_note: str, tp5: float, tp10: float, tp_note: str, sprd: float = 0.0) -> Path:
    """hist: gdp (year->level), debt (year->level), bal (year->IMF balance % GDP), g_base, trend."""
    cfg = C[cc]
    base = vintage
    bills_y1 = curve["1Y"]
    total = a["bills_out"] + a["coupon_out"]
    cost = (a["coupon_wavg"] * a["coupon_out"] + bills_y1 * a["bills_out"]) / total
    gdp_b = hist["gdp"][base]
    int_gdp = cost * total / gdp_b
    pd_b = -hist["bal"][base] - int_gdp
    tp = tp_curve(tp5, tp10, sprd)
    note_cost = q(f"REQUIRED: coupon-weighted {a['coupon_wavg']:.2f}% on coupon debt + bills at 1Y {bills_y1:.2f}%")
    note_pd = q(f"= IMF GG deficit {-hist['bal'][base]:.1f} minus modeled interest {int_gdp:.2f} % of GDP; current-deficit default")
    L = []
    L.append(f"# {cfg['name']} ({cc}) -- debt_model input file, vintage {vintage}, built {date.today()} by build_inputs.py from data/bloomberg/{fn}")
    L.append(f"# Snapshot {asof}; calendar-year buckets, base year {base}; {cfg['ccy']} billions; rates in %; shares as fractions.")
    L.append("# Format: section,item,sub_item,period,value,notes (lines starting with # are ignored). Assumptions live in debt_model.py / run_scenarios.py.")
    L.append("# DATA NOTES / CAVEATS")
    L.append(f"#  - debt = marketable central-government securities in the pull ({a['n_bonds']} coupon issues + {a['n_bills']} bills), domestic market only, deduped by ISIN;")
    L.append("#    central-bank holdings stay inside the stock (Amount Outstanding is used; its gap to Amount Issued is buybacks)")
    L.append(f"#  - linkers {a['linker_out']:,.0f}bn carried at real coupon + {INFLATION_ACCRUAL} pp inflation accrual; FRNs {a['frn_out']:,.0f}bn at current coupon")
    if a.get("mix_source") == "dated":
        L.append("#  - issuance_mix is ESTIMATED (no issue dates in the pull): each bond's issue date and original tenor come from market")
        L.append("#    conventions (maturity day/month, ticker, tenor labels) and from the chronological order of CUSIP/SEDOL/ISIN numbers;")
        L.append(f"#    composition = {a['mix_note']}; bills issuance = bills stock")
    else:
        L.append("#  - issuance_mix is INFERRED from the maturity profile (no issue dates in the pull): steady-state, annual issuance at")
        L.append("#    tenor k ~ maturing in year k minus year k+1 on a 3-year moving average; bills = bills stock")
    L.append("#    Override in run_scenarios.py / debt_model.py (ISSUANCE_MIX) if you have the debt office's issuance plan")
    L.append(f"#  - curve: {curve_note}")
    L.append(f"#  - term premia: 5Y/10Y from country_macro_comparison ({vintage} columns), other tenors shaped with the US ACM-style profile; static TP = implied"
             + (f"; the sovereign spread vs Bund ({sprd*100:.0f} bp, TP Build tab) is added FLAT to every tenor rather than shaped" if sprd else ""))
    L.append("#  - deficit: IMF GENERAL-government balance; primary deficit = that deficit minus modeled interest (avg cost x debt / GDP).")
    L.append("#    General government is wider than the central-government debt stock here, so it overstates the central primary deficit")
    if vintage == 2026:
        L.append("#  - nominal GDP 2026 = World Bank 2025 level x (1 + 2025 growth); ngdp_growth_pct = 2025 y/y; ngdp_growth_trend_pct = 2016-25 CAGR")
    else:
        L.append("#  - nominal GDP 2016 = World Bank actual; ngdp_growth_pct = 2016 y/y; ngdp_growth_trend_pct = REALIZED 2016-25 CAGR (for back-testing)")
    if asof.month < 10:
        L.append(f"#  - the pull is dated {asof}: maturities between then and end-{base} are folded into the first projection year")
    if cc == "US":
        L.append("#  - US pull covers T and B only: TIPS and FRNs are not included (user: immaterial)")
    if cc == "CN":
        L.append("#  - China: no separate bill ticker; sub-1y CGBs sit in the ladder, so the Bills bucket is in_ladder=1 and TP = 0 per instruction")
    L.append("section,item,sub_item,period,value,notes")
    L += [f"meta,country,,,{cfg['name']},", f"meta,country_code,,,{cc},", f"meta,currency_unit,,,{cfg['ccy']} billions,",
          f"meta,base_year,,,{base},{q('calendar-year buckets; snapshot ' + str(asof))}",
          "meta,horizon_years,,,10,", f"meta,curve_date,,,{asof},{q('bond pull date')}"]
    for y in sorted(hist["gdp"]):
        note = q("EXTRAPOLATED: 2025 x (1 + 2025 y/y growth)") if (y == 2026) else (q("World Bank WDI, current LCU") if y == min(hist["gdp"]) else "")
        L.append(f"history,nominal_gdp,,{y},{hist['gdp'][y]:.3f},{note}")
    L.append(f"history,ngdp_growth_pct,,{base},{hist['g_base']:.4f},{q('latest y/y nominal growth; current-growth default')}")
    L.append(f"history,ngdp_growth_trend_pct,,{base},{hist['trend']:.4f},{q('2016-2025 nominal GDP CAGR (World Bank); used by run_scenarios.py')}")
    if vintage == 2026 and cc in REAL_GROWTH_2026:
        rl, rt = REAL_GROWTH_2026[cc]
        L.append(f"history,real_gdp_growth_pct,,{base},{rl:.4f},{q('latest y/y real GDP growth (World Bank WDI, constant LCU, NY.GDP.MKTP.KN)')}")
        L.append(f"history,real_gdp_growth_trend_pct,,{base},{rt:.4f},{q('2016-2025 real GDP CAGR (World Bank); run_scenarios.py splits nominal growth into real + inflation')}")
    for y in sorted(hist["debt"]):
        L.append(f"history,debt_held_by_public,,{y},{hist['debt'][y]:.3f},{q(('REQUIRED: ' if y == base else '') + 'marketable central govt debt, SRCH as of ' + str(hist['debt_asof'][y]))}")
    L.append(f"history,avg_cost_pct,,{base},{cost:.4f},{note_cost}")
    for y in sorted(hist["bal"]):
        L.append(f"history,fiscal_deficit,,{y},{-hist['bal'][y] / 100 * hist['gdp'][y]:.3f},{q(f'IMF general govt balance {y} ({hist[chr(98)+chr(97)+chr(108)][y]:+.1f}% GDP) x GDP')}")
    L.append(f"history,primary_deficit_pct_gdp,,{base},{pd_b:.4f},{note_pd}")
    for b in BUCKETS:
        mat = cfg["frn_mat"] if b == "FRN" else BUCKET_MAT[b]
        L.append(f"bucket,{b},maturity_years,,{mat},")
        L.append(f"bucket,{b},price_tenor,,{BUCKET_TENOR[b]},")
        if b == "Bills" and cfg["bills"]:
            L.append(f"bucket,{b},in_ladder,,0,{q('bills are not in the ladder; base stock below')}")
            L.append(f"bucket,{b},base_outstanding,,{a['bills_out']:.3f},{q('bills outstanding at snapshot')}")
        else:
            L.append(f"bucket,{b},in_ladder,,1,")
    for b in BUCKETS:
        L.append(f"issuance_mix,{b},,,{a['mix'][b]:.6f},{q('estimated (see header)') if b == 'Bills' else ''}")
    years = sorted(set(a["ladder"]) | set(range(base + 1, base + 11)))
    for y in years:
        amt, cpn = a["ladder"].get(y, (0.0, 0.0))
        note = q("includes maturities between snapshot and year-end") if y == base + 1 else ""
        L.append(f"maturity_ladder,amount,,{y},{amt:.3f},{note}")
        L.append(f"maturity_ladder,coupon_pct,,{y},{cpn:.4f},")
    for lab, v in curve.items():
        L.append(f"spot_curve,{lab},,,{v:.3f},")
    for lab, v in tp.items():
        L.append(f"implied_tp,{lab},,,{v:.3f},{q(tp_note) if lab == '5Y' else ''}")
    for lab, v in tp.items():
        if lab != "O/N":
            L.append(f"static_tp,{lab},,,{v:.3f},")
    L.append("curve_param,on_wedge,,,0,")
    out_dir = OUT / str(vintage)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{cc}_debt_inputs.csv"
    out.write_text("\n".join(L) + "\n")
    return out


def build_all(vintages=VINTAGES):
    global SNAPSHOT, BASE_YEAR
    pulls, yields, macro = load_all(), read_yields(), read_macro()
    summary = []
    for vintage in vintages:
        for cc, cfg in C.items():
            asof, d, fn = pulls[(cc, vintage)]
            SNAPSHOT, BASE_YEAR = asof, vintage
            m = macro[cc]
            a = aggregate(d, cfg, vintage)
            a["mix_source"] = MIX_SOURCE[vintage].get(cc, "ladder")
            if a["mix_source"] == "dated":
                d16 = pulls[(cc, 2016)][1] if vintage == 2026 else None
                asof16 = pulls[(cc, 2016)][0] if vintage == 2026 else None
                a["mix"], est = dated_mix(cc, d, d16, asof16)
                t_now = asof.year + (asof.timetuple().tm_yday - 1) / 365.25
                rec = est.filter(pl.col("est_issue") >= t_now - WINDOW_YEARS)
                a["mix_note"] = (f"lines opened in the last {WINDOW_YEARS:g} years ({rec.height} issues, "
                                 f"{rec['amt'].sum()/1e9/WINDOW_YEARS:,.0f}bn/yr) by estimated original tenor")
            a16 = aggregate(pulls[(cc, 2016)][1], cfg, 2016)
            debt16 = a16["bills_out"] + a16["coupon_out"]
            cagr = ((m["gdp25"] / m["gdp16"]) ** (1 / 9) - 1) * 100
            if vintage == 2026:
                gdp26 = m["gdp25"] * (1 + m["g25"] / 100)
                hist = dict(gdp={2015: m["gdp15"], 2016: m["gdp16"], 2024: m["gdp24"], 2025: m["gdp25"], 2026: gdp26},
                            debt={2016: debt16, 2026: a["bills_out"] + a["coupon_out"]},
                            debt_asof={2016: pulls[(cc, 2016)][0], 2026: asof},
                            bal={2016: m["bal16"], 2026: m["bal26"]}, g_base=m["g25"], trend=cagr)
                curve = {"O/N": MARKET[cc]["O/N"], "1Y": MARKET[cc]["1Y"]}
                for k, v in MARKET[cc].items():
                    curve.setdefault(k, v)
                for yrs, yld in sorted(yields.get(cc, [])):
                    if yrs > 1.2:
                        curve[f"{yrs:g}Y"] = yld
                note, tp5, tp10, sprd = MARKET_NOTE[cc], m["tp5"], m["tp10"], m["sprd"]
            else:
                hist = dict(gdp={2015: m["gdp15"], 2016: m["gdp16"]}, debt={2016: debt16}, debt_asof={2016: asof},
                            bal={2016: m["bal16"]}, g_base=m["g16"], trend=cagr)
                mk = MARKET_2016[cc]
                curve = {k: mk[k] for k in ["O/N", "1Y", "2Y", "5Y", "10Y", "30Y"]}
                note, tp5, tp10, sprd = MARKET_NOTE_2016, m["tp5_16"], m["tp10_16"], m["sprd16"]
            path = write_csv(cc, vintage, a, hist, asof, curve, m, fn, note, tp5, tp10, m["tp_note"], sprd)
            summary.append((vintage, cc, path, a, curve))
    return summary


# =============================================================================================
#  Issue-date and original-tenor estimation  (the pull has no issue dates)
# =============================================================================================
# 1. Where a market convention pins the tenor, use it (US: 10y notes mature on the 15th of Feb/May/
#    Aug/Nov, 3y notes on the 15th of other months, 20y/30y bonds by remaining life; Germany: BKO=2y,
#    OBL=5y, DBR by maturity day/month; Italy & Denmark: tenor label in the Series column; long bonds
#    beyond the second-longest standard tenor).  Issue date = maturity - tenor.
# 2. Everything else is dated by its identifier: CUSIP letters, SEDOLs and ISIN numbers are allocated
#    sequentially in time, so the identifier value is interpolated between anchor points -- the
#    rule-based bonds above, the position of the 2016 snapshot (all bonds in the 2016 pull precede
#    all later ones), and the newest bond (= snapshot date).  Tenor = nearest standard tenor to the
#    implied life, never shorter than the remaining life.
# 3. Current issuance composition = lines opened in the last WINDOW years, by estimated tenor.
STD_TENORS = {
    "US": {"notes": [2, 3, 5, 7, 10], "bonds": [20, 30]},
    "CA": {"all": [2, 3, 5, 10, 30, 50]},
    "UK": {"all": [2, 3, 5, 7, 10, 15, 20, 25, 30, 40, 50]},
    "DE": {"all": [2, 5, 7, 10, 15, 30]},
    "FR": {"all": [2, 3, 5, 7, 10, 15, 20, 30, 50]},
    "IT": {"all": [2, 3, 5, 7, 10, 15, 20, 30, 50]},
    "CN": {"all": [1, 2, 3, 5, 7, 10, 20, 30, 50]},
    "DK": {"all": [2, 5, 10, 20, 30]},
    "AU": {"all": [3, 5, 7, 10, 12, 15, 20, 30]},
}
WINDOW_YEARS = 2.0
_B36 = {c: i for i, c in enumerate("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")}


def b36(sv: str) -> float:
    v = 0
    for ch in sv.upper():
        v = v * 36 + _B36.get(ch, 0)
    return float(v)


def seq_value(cc: str, isin: str, tic: str, series) -> tuple[str, float]:
    """(family, numeric position in the issue sequence)."""
    if cc == "US":
        cusip = isin[2:11]
        fam = "bonds" if cusip.startswith("912810") else "notes"
        return fam, (0 if cusip.startswith("912828") else 1) * 1e6 + b36(cusip[6:8])
    if cc == "CA":
        pair = isin[8:10]
        return "all", (0 if pair[0] >= "V" else 1) * 1e6 + b36(pair)       # letter cycle restarted at 'A' ~2012
    if cc == "UK":
        sedol = isin[4:11]
        old = sedol[0].isdigit() or sedol[:2] in ("BY", "BZ")                # pre-2017 SEDOL blocks
        return "all", (0 if old else 1) * 1e13 + b36(sedol)
    if cc == "FR":
        return "all", b36(isin[2:11])
    if cc in ("IT", "DK"):
        return "all", float(isin[2:11])
    if cc == "CN":
        return "all", b36(isin[7:11])
    if cc == "AU":
        try:
            return "all", float(series)
        except (TypeError, ValueError):
            return "all", -1.0
    if cc == "DE":
        return "all", 0.0            # fully rule-based
    raise KeyError(cc)


def rule_tenor(cc: str, r: dict, in16: bool) -> tuple[float, float] | None:
    """(original tenor, extra life at launch) from market conventions, or None if the rules cannot tell."""
    mat, rem, cpn, tic = r["mat"], r["yrs"], r["cpn"], r["tic"]
    lab = re.fullmatch(r"(\d+)Y", str(r["Series"]).strip()) if r["Series"] is not None else None
    if lab:
        return float(lab.group(1)), 0.0
    d, mth = mat.day, mat.month
    if cc == "US":
        if r["isin"][2:11].startswith("912810"):
            if BASE_YEAR < 2020:
                return 30.0, 0.0                                     # no 20y issuance 1986-2020
            return (30.0, 0.0) if rem > 20 else None                 # 20y vs 30y in 2040-46 decided by CUSIP order
        if d == 15:
            return (10.0, 0.0) if (mth in (2, 5, 8, 11) and (rem > 3 or cpn < 3.3)) else (3.0, 0.0)
        return None
    if cc == "DE":
        if tic == "BKO":
            return 2.0, 0.0
        if tic == "OBL":
            return 5.0, 0.0
        if mth == 5:
            return 15.0, 0.0
        if mth == 11:
            return 7.0, 0.0
        return (30.0, 0.0) if (rem > 15 or mth in (1, 7) or cpn >= 4) else (10.0, 0.0)
    if cc == "CA":                                                   # Bank of Canada benchmark cycle
        if rem > 35:
            return 50.0, 0.0
        if d == 1 and mth in (2, 5, 8, 11) and not in16:
            return (2.0, 0.0) if rem <= 2.05 else (3.0, 0.0)
        if d == 1 and mth in (3, 9) and not in16 and rem <= 5.05:
            return 5.0, 0.0
        if d == 1 and mth in (6, 12):
            if rem > 12 or in16:
                return 30.0, 1.0                                     # 30y lines launch with ~31y of life
            return 10.0, 0.1
        return None
    if cc == "FR":
        if rem > 33:
            return 50.0, 0.0
        if d == 25 and mth in (2, 5, 11) and rem >= 11 and not in16:
            ten = min([15.0, 20.0, 30.0], key=lambda t: abs(t - (rem + 0.7)))
            return (ten, 0.7) if ten >= rem else None
        return None
    if cc == "CN" and rem > 33:
        return 50.0, 0.0
    if cc == "AU" and rem > 20:
        return 30.0, 0.0
    return None


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


def _fit_anchors(anchors: list[tuple[float, float]], max_shift: float = 1.5) -> tuple[list[float], list[float]]:
    """Monotone (time non-decreasing in identifier) fit; anchors the fit has to move > max_shift years are outliers."""
    pts = sorted(anchors)
    for _ in range(3):
        ys = [-v for v in isotonic_decreasing([-t for _, t in pts])]
        bad = [i for i, (p, y) in enumerate(zip(pts, ys)) if abs(p[1] - y) > max_shift]
        if not bad or len(pts) - len(bad) < 2:
            break
        pts = [p for i, p in enumerate(pts) if i not in bad]
    ys = [-v for v in isotonic_decreasing([-t for _, t in pts])]
    return [p[0] for p in pts], ys


def _split_x(lst: list[dict]) -> float | None:
    """Identifier value separating pre- and post-2016 bonds, chosen to minimise misclassifications."""
    srt = sorted(lst, key=lambda r: r["x"])
    n_old = sum(r["in16"] for r in srt)
    if n_old == 0 or n_old == len(srt):
        return None
    best, best_err = None, 10 ** 9
    for i in range(1, len(srt)):
        err = sum(1 for r in srt[:i] if not r["in16"]) + sum(1 for r in srt[i:] if r["in16"])
        if err < best_err:
            best, best_err = (srt[i - 1]["x"] + srt[i]["x"]) / 2, err
    return best


def estimate_issue(cc: str, d26: pl.DataFrame, d16: pl.DataFrame | None, asof16: date | None) -> pl.DataFrame:
    """Adds est_issue (decimal year), est_tenor (years), dated_by ('rule'|'seq') to the 2026 coupon bonds."""
    cp = d26.filter(~pl.col("is_bill") & pl.col("isin").is_not_null()).with_columns(pl.col("Series").cast(pl.Utf8, strict=False))
    in16 = set(d16["isin"].to_list()) if d16 is not None else set()
    t_now = SNAPSHOT.year + (SNAPSHOT.timetuple().tm_yday - 1) / 365.25
    t16 = asof16.year + (asof16.timetuple().tm_yday - 1) / 365.25 if asof16 else 2016.75
    fams: dict[str, list[dict]] = {}
    for r in cp.to_dicts():
        fam, x = seq_value(cc, r["isin"], r["tic"], r["Series"])
        r["x"], r["in16"] = x, r["isin"] in in16
        r["mat_t"] = r["mat"].year + (r["mat"].timetuple().tm_yday - 1) / 365.25
        r["rule"] = rule_tenor(cc, r, r["in16"])
        fams.setdefault(fam, []).append(r)
    out = []
    for fam, lst in fams.items():
        std = STD_TENORS[cc].get(fam) or STD_TENORS[cc]["all"]
        anchors = [(r["x"], min(r["mat_t"] - r["rule"][0] - r["rule"][1], t_now)) for r in lst if r["rule"] is not None]
        sx = _split_x(lst)
        if sx is not None:
            anchors.append((sx, t16))
        anchors.append((max(r["x"] for r in lst), t_now))
        xs, ys = _fit_anchors(anchors)
        for r in lst:
            if r["rule"] is not None:
                ten, t, how = r["rule"][0], min(r["mat_t"] - r["rule"][0] - r["rule"][1], t_now), "rule"
            else:
                t = min(_interp(xs, ys, r["x"]), t_now)
                life = r["mat_t"] - t
                cands = [s for s in std if s >= r["yrs"] - 0.05] or [std[-1]]
                ten, how = float(min(cands, key=lambda s: abs(s - life))), "seq"
            out.append(dict(isin=r["isin"], est_issue=t, est_tenor=ten, dated_by=how))
    return cp.join(pl.DataFrame(out), on="isin")


def dated_mix(cc: str, d26: pl.DataFrame, d16, asof16) -> tuple[dict, pl.DataFrame]:
    est = estimate_issue(cc, d26, d16, asof16)
    t_now = SNAPSHOT.year + (SNAPSHOT.timetuple().tm_yday - 1) / 365.25
    recent = est.filter((pl.col("est_issue") >= t_now - WINDOW_YEARS) & ~pl.col("is_frn"))
    mix = {b: 0.0 for b in BUCKETS}
    for ten, amt in recent.select("est_tenor", "amt").iter_rows():
        mix[bucket_of(int(round(ten)))] += amt / 1e9 / WINDOW_YEARS
    mix["FRN"] = d26.filter(pl.col("is_frn"))["amt"].sum() / 1e9 / C[cc]["frn_mat"]
    mix["Bills"] += d26.filter(pl.col("is_bill"))["amt"].sum() / 1e9
    tot = sum(mix.values())
    mix = {b: round(v / tot, 6) for b, v in mix.items()}
    big = max(mix, key=mix.get)
    mix[big] = round(mix[big] + (1.0 - sum(mix.values())), 6)
    return mix, est


def dating_report():
    pulls = load_all()
    t_now = 2026 + (SNAPSHOT.timetuple().tm_yday - 1) / 365.25
    for cc in C:
        asof, d, _ = pulls[(cc, 2026)]
        d16, asof16 = (pulls[(cc, 2016)][1], pulls[(cc, 2016)][0]) if (cc, 2016) in pulls else (None, None)
        mix, est = dated_mix(cc, d, d16, asof16)
        rec = est.filter(pl.col("est_issue") >= t_now - WINDOW_YEARS)
        gap = d.select(((pl.col("Amt Issued").cast(pl.Float64, strict=False) - pl.col("amt")).sum() / pl.col("amt").sum() * 100)).item()
        print(f"\n{cc}: dated mix {{{', '.join(f'{b}: {v:.3f}' for b, v in mix.items())}}}   coupon lines in window: {rec.height} "
              f"({rec['amt'].sum()/1e9/WINDOW_YEARS:,.0f}bn/yr; rule-dated {est.filter(pl.col('dated_by')=='rule').height}/{est.height})   issued-minus-out: {gap:.1f}%")
        print("    newest:", [(r["Security Name"], round(r["est_issue"], 1), r["est_tenor"]) for r in rec.sort("est_issue", descending=True).head(10).to_dicts()])
        print("    window edge:", [(r["Security Name"], round(r["est_issue"], 1), r["est_tenor"]) for r in rec.sort("est_issue").head(5).to_dicts()])


if __name__ == "__main__":
    if "--dating" in sys.argv:
        dating_report()
    elif "--diagnose" not in sys.argv:          # --diagnose is handled where aggregate() is defined
        for vintage, cc, path, a, curve in build_all():
            print(f"{vintage} {cc}: wrote {path.relative_to(ROOT)}   debt={a['bills_out']+a['coupon_out']:,.0f}  bills={a['bills_out']:,.0f}  "
                  f"cost~{a['coupon_wavg']:.2f}  mix={a.get('mix_source')}  curve={ {k: round(v, 2) for k, v in curve.items() if k in ('O/N','1Y','10Y')} }")
