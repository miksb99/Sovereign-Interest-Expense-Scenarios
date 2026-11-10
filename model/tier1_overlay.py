#!/usr/bin/env python3
"""
tier1_overlay.py -- sub-sovereign / quasi-sovereign ("Tier 1") debt overlay on the sovereign interest model.

A deliberately simple block model, one block per issuer group, driven by three assumptions each with a
bull / base / bear setting:  (1) growth of the block's debt stock, (2) its weighted average maturity (WAM),
(3) its spread over the sovereign curve.  Everything else (curve, GDP, horizon) is inherited from the
sovereign run so the two can be added.

Per block and year:
    stock_t     = stock_{t-1} * (1 + g_t)
    rollover    = stock_{t-1} / max(T, 1)    T = issue tenor ~ 2 x WAM  (uniform ladder; sub-1y books roll fully each year)
    issued_t    = max(rollover + (stock_t - stock_{t-1}), 0)      priced at  sovereign forward(T, t) + spread
    retired_t   = stock_{t-1} + issued_t - stock_t                 leaves at the block's average cost
    cost_t      = (cost_{t-1} * (stock_{t-1} - retired_t) + y_t * issued_t) / stock_t
    interest_t  = cost_t * average stock
Starting cost = vintage-weighted average of (sovereign yield at tenor T when each vintage was issued + spread),
interpolating the 2016 and 2026 sovereign curves, with a per-country premium for pre-2016 vintages.

Outputs (outputs/2026/):
    TIER1_assumptions.csv       the explicit bull/base/bear settings per block
    TIER1_blocks.csv            block x scenario x year paths (stock, cost, interest, % GDP)
    TIER1_grid.csv              27-combination grid per country (growth x WAM x spread) on market forwards
    CONSOLIDATED_paths.csv      sovereign + tier-1 by sovereign curve case x tier-1 case, with r-vs-g metrics
"""
from __future__ import annotations
from pathlib import Path
import polars as pl
import debt_model as dm
import run_scenarios as rs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # repository root (model/ sits one level down)
DATA = ROOT / "data"
T1 = DATA / "tier1"
OUT = ROOT / "outputs" / "2026"
BASE_YEAR, H = 2026, 10
YEARS = list(range(BASE_YEAR + 1, BASE_YEAR + H + 1))
# Tier-1 settings per JOINT case as (growth case, WAM case, spread case) of the three levers.  Repression: issuers term out at
# capped rates (longer WAM) and captive banks absorb provinces / semis / Laender (tight spread) while the stock grows at its
# middle historical pace.  Bull: middle settings through the capex boom (2027-30), then the tight spread and longer WAM once
# the cuts arrive (blend in 2031, full from 2032; see run_scenarios.bull_phase2_weight); growth at the middle pace throughout.
T1_CASE = {"bull": ("base", "bull", "bull"), "base": ("base", "base", "base"), "bear": ("bear", "bear", "bear"),
           "repression": ("base", "bull", "bull")}

# ---- average 10y yield 2006-15 minus the 2016 10y: premium applied to pre-2016 vintages when estimating the
#      starting coupon of long-WAM stocks (estimates)
PRE2016_PREMIUM = {"US": 0.7, "CA": 1.1, "UK": 1.6, "DE": 2.1, "FR": 2.2, "IT": 2.4, "CN": 0.3, "DK": 2.2, "AU": 1.7}

# ---- block definitions ------------------------------------------------------------------------------------
# growth: % per year of the block stock, (bull, base, bear); a tuple (start, end) glides linearly over the horizon
# stress: bp added to the wider of through-cycle / current spread in the bear case
# fiscal: True = counts in the base consolidated picture; False = exposure variant only
BLOCKS = [
    dict(cc="CA", block="CA_provinces", file="canada_tier1_provincials.csv", issuers=["AGGREGATE"], unit=1.0,
         growth="rule", stress=25, fiscal=True, why="growth rule on the four-province aggregate"),
    dict(cc="AU", block="AU_semis", file="australia_tier1_semis.csv", issuers=["AGGREGATE"], unit=1.0,
         growth="rule", stress=30, fiscal=True, why="growth rule on the eight-state aggregate"),
    dict(cc="CN", block="CN_LGB", file="china_tier1_local.csv", issuers=["CHINA_LGB"], unit=1000.0, vintage_floor=2015,
         growth="rule_cn_combined", stress=15, fiscal=True, why="combined LGB+LGFV stock: bull = last year's pace, base = 5y pace decelerating to last year's, bear = 5y pace held; the 2016-19 window is excluded (loan-to-bond reclassification); LGBs absorb what the swap retires"),
    dict(cc="CN", block="CN_LGFV_AAA", file="china_tier1_local.csv", issuers=["LGFV_AAA"], unit=1000.0,
         growth=(-5.0, -3.0, -3.0), stress=100, fiscal=True, why="swap retires LGFV paper (legislated to 2028): -3%/yr in base and bear, -5% bull; the bear stresses price, not the swap"),
    dict(cc="CN", block="CN_LGFV_AAplus", file="china_tier1_local.csv", issuers=["LGFV_AAplus"], unit=1000.0,
         growth=(-5.0, -3.0, -3.0), stress=150, fiscal=True, why="as above; 2018/2022 stress saw AA spreads 300-450bp"),
    dict(cc="CN", block="CN_LGFV_AA_below", file="china_tier1_local.csv", issuers=["LGFV_AA_below"], unit=1000.0,
         growth=(-6.0, -3.0, -3.0), stress=250, fiscal=True, why="weak credits retired first; RMB2.3tn reduction pledged by 2028"),
    # LGFV bank loans, trust and other non-bond borrowing: not in any Bloomberg screen.  Notes: total LGFV interest-bearing debt
    # RMB 55-60tn of which bonds ~30%, so ~RMB 42tn outside the bond series.  Priced like LGFV loans (~4.5% today), 3y WAM, same swap path.
    dict(cc="CN", block="CN_LGFV_loans", file="china_tier1_local.csv", issuers=["LGFV_AA_below"], unit=1000.0, fixed_stock=42000.0,
         wam_override=3.0, sp_override=(1.5, 1.0), growth=(-5.0, -3.0, -3.0), stress=250, fiscal=True,
         why="LGFV bank/trust loans ~RMB 42tn (notes: bonds are ~30% of RMB 55-60tn); hardcoded, not a securities screen; follows the swap path"),
    dict(cc="DE", block="DE_Laender", file="germany_tier1_laender.csv", issuers=["AGGREGATE"], unit=1.0,
         growth="rule", stress=15, fiscal=True, why="growth rule on the Laender aggregate (2016-19 was deleveraging, so bull is negative)"),
    dict(cc="FR", block="FR_CADES", file="france_tier1_agencies.csv", issuers=["CADES"], unit=1.0,
         growth="rule", stress=10, fiscal=True, why="legislated EUR16bn/yr amortisation vs new transfers (EUR15bn in 2026); sunset 2033"),
    dict(cc="FR", block="FR_UNEDIC", file="france_tier1_agencies.csv", issuers=["UNEDIC"], unit=1.0,
         growth="rule", stress=10, fiscal=True, why="running surpluses, state siphons receipts"),
    dict(cc="FR", block="FR_ACOSS", file="france_tier1_agencies.csv", issuers=["ACOSS"], unit=1.0,
         growth="rule", stress=10, fiscal=True, why="social-security deficit (-EUR21.6bn 2025) accumulates in bills with no amortisation vehicle"),
    dict(cc="FR", block="FR_dev_banks", file="france_tier1_agencies.csv", issuers=["SFILFR_CAFFIL", "BPIFRA", "AGFRNC", "IDFMOB"], unit=1.0,
         growth="rule", stress=10, fiscal=False, why="asset-backed development banks: exposure variant only (double-counts if added)"),
    dict(cc="IT", block="IT_core", file="italy_tier1_quasi.csv", issuers=["CDP_BONDS", "FERRIT", "LAZIO", "LOMBAR", "PIEMON", "SICILY"], unit=1.0,
         growth="rule", stress=10, fiscal=True, why="CDP bonds + FS + amortising regional sinkers; tiny"),
    dict(cc="IT", block="IT_postal", file="italy_tier1_quasi.csv", issuers=["CDP_POSTAL"], unit=1.0,
         growth="rule", stress=10, fiscal=False, why="state-guaranteed, putable at par daily; serviced by CDP asset income: exposure variant"),
]
WAM_MULT = {"bull": 1.3, "base": 1.0, "bear": 0.7}
# Starting average cost, % : published effective interest rates (interest paid / average debt, latest year)
# ON 3.3 / QC 3.7 / AB 3.1 / BC 3.2 -> CA 3.45; NSW 3.7 / VIC 4.6 / QLD 3.8 / WA 3.3 -> AU 3.9; MoF LGB average coupon ~3.1;
# chengtou by bucket ~3.6 / 4.3 / 5.2 (blended ~4.5 per notes); NRW 1.8 / city-states 1.6 -> Laender 1.7; CADES 1.9, Unedic 1.4,
# ACOSS ~ESTR+8bp 3.0; SFIL/Bpifrance 2.4; CDP bonds/FS 3.0; CDP postal all-in 2.8 (incl. Poste fee).
COST0 = {"CA_provinces": 3.45, "AU_semis": 3.9, "CN_LGB": 3.1, "CN_LGFV_AAA": 3.6, "CN_LGFV_AAplus": 4.3, "CN_LGFV_AA_below": 5.2, "CN_LGFV_loans": 4.5,
         "DE_Laender": 1.7, "FR_CADES": 1.9, "FR_UNEDIC": 1.4, "FR_ACOSS": 3.0, "FR_dev_banks": 2.4, "IT_core": 3.0, "IT_postal": 2.8}
# Tier-1 sector's own 2026 budget balance (surplus +), % of GDP, already inside the IMF general-government deficit used by the
# sovereign run.  The consolidated view removes it from the sovereign's primary deficit so that sub-national borrowing is not
# counted twice (once as central debt growth, once as tier-1 stock growth).  China: LGB net issuance (special bonds are in the
# official deficit).  France/Italy: net debt change of the fiscal blocks.
T1_BALANCE_SHARE_SRC = {"CA": ("AGGREGATE", "budget_balance_cad_bn"), "AU": ("AGGREGATE", "budget_balance_aud_bn"),
                        "DE": ("AGGREGATE", "net_debt_change_eur_bn")}   # DE AGGREGATE row holds the Finanzierungssaldo (surplus +)


def stock_at(df: pl.DataFrame, issuers: list[str], year: int, dcol: str, ycol: str, unit: float) -> float:
    return df.filter(pl.col("issuer").is_in(issuers) & (pl.col(ycol) == year))[dcol].sum() * unit


def growth_rule(df, issuers, dcol, ycol, unit) -> tuple[float, float, float]:
    """(bull, base, bear) % per year from three historical windows -- the 2016-19 (pre-COVID) CAGR, the 2021-26 five-year
    CAGR and last year's growth -- ranked so that bull is the slowest pace and bear the fastest."""
    s = {y: stock_at(df, issuers, y, dcol, ycol, unit) for y in (2016, 2019, 2021, 2025, 2026)}
    pre = ((s[2019] / s[2016]) ** (1 / 3) - 1) * 100
    five = ((s[2026] / s[2021]) ** (1 / 5) - 1) * 100
    last = (s[2026] / s[2025] - 1) * 100
    bull, base, bear = sorted([pre, five, last])
    return bull, base, bear


def load_block(b: dict) -> dict:
    df = pl.read_csv(T1 / b["file"], infer_schema_length=1000)
    ycol = [c for c in df.columns if c.startswith(("fy_end", "cal_year"))][0]
    dcol = [c for c in df.columns if c.startswith("total_debt")][0]
    bcol = [c for c in df.columns if c.startswith(("budget_balance", "net_issuance", "net_debt_change"))][0]
    rows = df.filter(pl.col("issuer").is_in(b["issuers"]) & (pl.col(ycol) == BASE_YEAR))
    stock = rows[dcol].sum() * b["unit"]
    w = (rows[dcol] * rows["wam_years"]).sum() / rows[dcol].sum()
    tc = (rows[dcol] * rows["spread_bp_throughcycle"]).sum() / rows[dcol].sum() / 100
    cur = (rows[dcol] * rows["spread_bp_current_oct2026"]).sum() / rows[dcol].sum() / 100
    prev = df.filter(pl.col("issuer").is_in(b["issuers"]) & (pl.col(ycol) == BASE_YEAR - 1))[dcol].sum() * b["unit"]
    first = df.filter(pl.col("issuer").is_in(b["issuers"]) & (pl.col(ycol) == 2016))[dcol].sum() * b["unit"]
    if b.get("fixed_stock"):                      # block defined by a hardcoded stock rather than file rows
        stock, prev, first = b["fixed_stock"], b["fixed_stock"] / 0.97, float("nan")
    if b.get("wam_override"):
        w = b["wam_override"]
    if b.get("sp_override"):
        tc, cur = b["sp_override"]
    out = dict(stock=stock, wam=w, sp_tc=tc, sp_cur=cur, stock_prev=prev, stock_2016=first,
               cagr=((stock / first) ** (1 / 10) - 1) * 100 if first > 0 else float("nan"))
    if b.get("growth") == "rule":
        out["growth"] = growth_rule(df, b["issuers"], dcol, ycol, b["unit"])
    elif b.get("growth") == "rule_cn_combined":          # rule on LGB + LGFV together; LGB absorbs what the swap retires
        # The 2016-19 window is dropped for China: it was mostly the loan-to-bond reclassification, not borrowing.
        s5 = stock_at(df, ["AGGREGATE"], BASE_YEAR, dcol, ycol, b["unit"]) / stock_at(df, ["AGGREGATE"], BASE_YEAR - 5, dcol, ycol, b["unit"])
        five = (s5 ** (1 / 5) - 1) * 100
        last = (stock_at(df, ["AGGREGATE"], BASE_YEAR, dcol, ycol, b["unit"]) / stock_at(df, ["AGGREGATE"], BASE_YEAR - 1, dcol, ycol, b["unit"]) - 1) * 100
        out["growth_combined"] = (min(five, last), (five, min(five, last)), five)   # bull: last year's pace; base: 5y pace decelerating to it; bear: 5y pace held
        out["combined_stock"] = stock_at(df, ["AGGREGATE"], BASE_YEAR, dcol, ycol, b["unit"])
    return out


def spread_case(blk: dict, case: str, stress: float) -> float:
    if case == "bull":
        return min(blk["sp_cur"], blk["sp_tc"] - 0.10)
    if case == "base":
        return blk["sp_tc"]
    return max(blk["sp_cur"], blk["sp_tc"]) + stress / 100


def growth_path(spec, case: str) -> dict[int, float]:
    if isinstance(spec, dict):                       # pre-computed per-year path
        return spec[case]
    g = spec[{"bull": 0, "base": 1, "bear": 2}[case]]
    if isinstance(g, tuple):
        a, z = g
        return {y: a + (z - a) * (i / (H - 1)) for i, y in enumerate(YEARS)}
    return {y: float(g) for y in YEARS}


def t1_settings(blk: dict, case: str) -> tuple[dict[int, float], dict[int, float], dict[int, float]]:
    """(growth path, issue tenor T by year, spread by year) of a block under a joint case (see T1_CASE)."""
    gcase, wcase, scase = T1_CASE[case]
    T1, sp1 = blk["T"] * WAM_MULT[wcase], spread_case(blk, scase, blk["stress"])
    if case == "bull":                                    # two phases: middle settings in the boom, tight / long after the cuts
        T0, sp0 = blk["T"] * WAM_MULT["base"], spread_case(blk, "base", blk["stress"])
        w = {y: rs.bull_phase2_weight(y, BASE_YEAR) for y in YEARS}
        return growth_path(blk["growth"], gcase), {y: T0 + (T1 - T0) * w[y] for y in YEARS}, {y: sp0 + (sp1 - sp0) * w[y] for y in YEARS}
    return growth_path(blk["growth"], gcase), {y: T1 for y in YEARS}, {y: sp1 for y in YEARS}


def t1_rate(mat: dm.RateMatrix, T: dict[int, float], sp: dict[int, float]) -> dict[int, float]:
    """New-issue rate by year: the sovereign forward for that year's issue tenor plus that year's spread."""
    return {y: mat[(tenor_label(T[y]), y)] + sp[y] for y in YEARS}


def t1_tenors(blocks: list[dict], cc: str) -> list[str]:
    """Every tenor label the blocks of a country can be priced at (lever settings and the blended joint-case years)."""
    labs = {tenor_label(bl["T"] * m) for bl in blocks if bl["cc"] == cc for m in WAM_MULT.values()}
    labs |= {tenor_label(T) for bl in blocks if bl["cc"] == cc for case in rs.CASES for T in t1_settings(bl, case)[1].values()}
    return sorted(labs)


def tenor_label(T: float) -> str:
    T = min(max(T, 1.0), 30.0)
    return f"{T:g}Y"


def starting_cost(cc: str, curves16: dm.CurveSet, curves26: dm.CurveSet, T: float, spread: float, floor: int | None) -> float:
    """Vintage-weighted coupon: uniform vintages over the last T years, priced at the tenor-T sovereign yield then + spread."""
    n = max(int(round(T)), 1)
    tot = 0.0
    for k in range(n):
        v = BASE_YEAR - k - 0.5
        if floor and v < floor:
            v = floor
        if v >= 2016:
            w = (v - 2016) / 10
            y = curves16.spot(T) * (1 - w) + curves26.spot(T) * w
        else:
            y = curves16.spot(T) + PRE2016_PREMIUM[cc]
        tot += y + spread
    return tot / n


def roll(stock0: float, cost0: float, g: dict[int, float], T, rate: dict[int, float]) -> list[dict]:
    """T = issue tenor (years), a scalar or {year: T}; one T-th of the stock rolls each year."""
    D, c = stock0, cost0
    out = [dict(year=BASE_YEAR, stock=D, cost=c, interest=c / 100 * D, issued=None, new_rate=None)]
    for y in YEARS:
        Ty = T[y] if isinstance(T, dict) else T
        Dn = D * (1 + g[y] / 100)
        issued = max(D / max(Ty, 1.0) + (Dn - D), 0.0)       # at most the whole stock rolls in a year
        retired = D + issued - Dn
        cn = ((c * (D - retired) + rate[y] * issued) / Dn) if Dn > 0 else c
        out.append(dict(year=y, stock=Dn, cost=cn, interest=cn / 100 * (D + Dn) / 2, issued=issued, new_rate=rate[y]))
        D, c = Dn, cn
    return out


T1_COUNTRIES = ["CA", "AU", "CN", "DE", "FR", "IT"]


def prepare_blocks(inputs16: dict) -> list[dict]:
    """Load every block, attach T, starting cost and the growth paths (incl. the derived LGB path)."""
    blocks = []
    for b in BLOCKS:
        blk = dict(b)
        blk.update(load_block(b))          # computed fields (incl. the growth rule) win over the definition
        blk["T"] = 2 * blk["wam"]
        blk["cost0"] = COST0[blk["block"]]
        blocks.append(blk)
    lgfv = [bl for bl in blocks if bl["block"].startswith("CN_LGFV") and bl["block"] != "CN_LGFV_loans"]
    lgb = [bl for bl in blocks if bl["block"] == "CN_LGB"][0]
    lgb_paths = {}
    for case in ("bull", "base", "bear"):
        gpath = growth_path(lgb["growth_combined"], case)
        comb, lg, path, prev = lgb["combined_stock"], lgb["stock"], {}, lgb["stock"]
        lf = {bl["block"]: bl["stock"] for bl in lgfv}
        for y in YEARS:
            comb *= 1 + gpath[y] / 100
            for bl in lgfv:
                lf[bl["block"]] *= 1 + growth_path(bl["growth"], case)[y] / 100
            lg_new = comb - sum(lf.values())
            path[y] = (lg_new / prev - 1) * 100
            prev = lg_new
        lgb_paths[case] = path
    lgb["growth"] = lgb_paths
    return blocks


def t1_balance_share(blocks: list[dict], gdp0: dict[str, float]) -> dict[str, float]:
    """Tier-1 sector's own 2026 deficit as % of GDP (+ = deficit), to remove from the sovereign's GG primary deficit."""
    t1_bal = {}
    for cc in T1_COUNTRIES:
        if cc in T1_BALANCE_SHARE_SRC:
            iss, col = T1_BALANCE_SHARE_SRC[cc]
            b0 = [b for b in BLOCKS if b["cc"] == cc][0]
            df = pl.read_csv(T1 / b0["file"], infer_schema_length=1000)
            ycol = [c for c in df.columns if c.startswith(("fy_end", "cal_year"))][0]
            bal = df.filter((pl.col("issuer") == iss) & (pl.col(ycol) == BASE_YEAR))[col][0]
            t1_bal[cc] = -bal / gdp0[cc] * 100          # all three columns are surplus-positive balances at AGGREGATE level
        elif cc == "CN":
            df = pl.read_csv(T1 / "china_tier1_local.csv", infer_schema_length=1000)
            t1_bal[cc] = df.filter((pl.col("issuer") == "CHINA_LGB") & (pl.col("cal_year_end") == BASE_YEAR))["net_issuance_cny_tn"][0] * 1000 / gdp0[cc] * 100
        else:   # FR, IT: net debt change of the fiscal blocks
            fb = [bl for bl in blocks if bl["cc"] == cc and bl["fiscal"]]
            t1_bal[cc] = sum(bl["stock"] - bl["stock_prev"] for bl in fb) / gdp0[cc] * 100
    return t1_bal


def main() -> None:
    inputs26 = {cc: dm.load_inputs(DATA / "inputs" / "2026" / f"{cc}_debt_inputs.csv") for cc in T1_COUNTRIES}
    inputs16 = {cc: dm.load_inputs(DATA / "inputs" / "2016" / f"{cc}_debt_inputs.csv") for cc in inputs26}
    det = pl.read_csv(OUT / "ALL_detail_paths.csv")
    base_sov = det.filter((pl.col("deficit_scenario") == "holds") & (pl.col("growth_scenario") == "base"))
    gdp = {cc: {y: v for y, v in base_sov.filter((pl.col("country") == cc) & (pl.col("rate_scenario") == "market")).select("year", "nominal_gdp").iter_rows()} for cc in inputs26}
    blocks = prepare_blocks(inputs16)
    mats = {}
    for cc, inp in inputs26.items():
        tenors = t1_tenors(blocks, cc)
        specs, roles = rs.curve_scenarios(inp, 2026, tenors), rs.curve_roles(inp)
        mats[cc] = {role: dm.build_rate_matrix(inp, specs.get(name), tenors) for role, name in roles.items()}

    # ---- assumptions table + starting costs ------------------------------------------------------------
    arows, prows, grows = [], [], []
    for bl in blocks:
        cc = bl["cc"]
        bl["cost0_vintage"] = starting_cost(cc, inputs16[cc].curves, inputs26[cc].curves, bl["T"], bl["sp_tc"], bl.get("vintage_floor"))
        for case in rs.CASES:
            gp, T, sp = t1_settings(bl, case)
            y1, yH = YEARS[0], YEARS[-1]
            arows.append(dict(country=cc, block=bl["block"], fiscal=bl["fiscal"], case=case, stock_2026=bl["stock"],
                              stock_pct_gdp=bl["stock"] / gdp[cc][BASE_YEAR] * 100, cagr_2016_26=bl["cagr"], start_cost_pct=bl["cost0"], start_cost_vintage_check=bl["cost0_vintage"],
                              growth_yr1=gp[y1], growth_yr10=gp[yH], wam=T[yH] / 2, wam_yr1=T[y1] / 2, issue_tenor=T[yH],
                              spread_pp=sp[yH], spread_pp_yr1=sp[y1], rationale=bl["why"]))
        # full 27-grid on market forwards (isolates the three levers) + the joint cases on each sovereign curve
        for gcase in ("bull", "base", "bear"):
            for wcase in ("bull", "base", "bear"):
                for scase in ("bull", "base", "bear"):
                    T = bl["T"] * WAM_MULT[wcase]
                    sp = spread_case(bl, scase, bl["stress"])
                    rate = {y: mats[cc]["base"][(tenor_label(T), y)] + sp for y in YEARS}
                    path = roll(bl["stock"], bl["cost0"], growth_path(bl["growth"], gcase), T, rate)
                    for r in path:
                        grows.append(dict(country=cc, block=bl["block"], fiscal=bl["fiscal"], growth_case=gcase, wam_case=wcase, spread_case=scase,
                                          **r, interest_pct_gdp=r["interest"] / gdp[cc][r["year"]] * 100))
        for sov_case in rs.CASES:
            for t1_case in rs.CASES:
                gp, T, sp = t1_settings(bl, t1_case)
                path = roll(bl["stock"], bl["cost0"], gp, T, t1_rate(mats[cc][sov_case], T, sp))
                for r in path:
                    prows.append(dict(country=cc, block=bl["block"], fiscal=bl["fiscal"], sov_case=sov_case, t1_case=t1_case, **r,
                                      interest_pct_gdp=r["interest"] / gdp[cc][r["year"]] * 100, stock_pct_gdp=r["stock"] / gdp[cc][r["year"]] * 100))
    assumptions = pl.DataFrame(arows)
    blocks_df = pl.DataFrame(prows)
    grid = pl.DataFrame(grows)
    assumptions.write_csv(OUT / "TIER1_assumptions.csv")
    blocks_df.write_csv(OUT / "TIER1_blocks.csv")
    grid.write_csv(OUT / "TIER1_grid.csv")

    # ---- consolidated: sovereign re-run on a CENTRAL primary deficit (GG deficit less the tier-1 sector's own balance)
    #      + fiscal tier-1 blocks, each under its JOINT case (growth, deficit path and curve of the sovereign case; growth,
    #      WAM and spread of the tier-1 case).  The sovereign-only lines in the main report keep the GG deficit.
    t1_bal = t1_balance_share(blocks, {cc: gdp[cc][BASE_YEAR] for cc in inputs26})
    # t1_bal is the sub-national DEFICIT share (+ = deficit) to remove from the GG primary deficit
    sov_central, sov_growth = {}, {}
    for cc, inp in inputs26.items():
        pd_gg = inp.primary_deficit_current
        pd_central = pd_gg - t1_bal[cc]
        inp.primary_deficit_current = pd_central                 # the deficit cases glide from (and target relative to) the central figure
        st = rs.settings_for(inp, 2026)
        scen = dm.resolve_scenarios(inp, st["growth"], st["deficit"], st["mix"], st["rates"])
        inp.primary_deficit_current = pd_gg
        for sov_case, sov_name in rs.curve_roles(inp).items():
            g, d = scen.growth[rs.CASE_GROWTH[sov_case]], scen.deficit[rs.case_deficit(cc, sov_case)]
            sov_central[(cc, sov_case)] = pl.DataFrame(dm.project(inp, scen.rates[sov_name], g, d, scen.issuance[rs.case_mix(cc, sov_case)]))
            sov_growth[(cc, sov_case)] = g[YEARS[0]]
        print(f"{cc}: GG primary deficit {pd_gg:+.2f}% GDP, tier-1 sector balance share {t1_bal[cc]:+.2f} -> central {pd_central:+.2f}")
    crows = []
    for cc, inp in inputs26.items():
        for sov_case, sov_name in rs.curve_roles(inp).items():
            sov = sov_central[(cc, sov_case)].sort("year")
            sov_gg = det.filter((pl.col("country") == cc) & (pl.col("rate_scenario") == sov_name) & (pl.col("deficit_scenario") == rs.case_deficit(cc, sov_case))
                                & (pl.col("growth_scenario") == rs.CASE_GROWTH[sov_case])).sort("year")
            for t1_case in rs.CASES:
                for variant, fiscal_only in (("fiscal", True), ("incl_exposure", False)):
                    t1 = blocks_df.filter((pl.col("country") == cc) & (pl.col("sov_case") == sov_case) & (pl.col("t1_case") == t1_case)
                                          & ((pl.col("fiscal")) if fiscal_only else pl.lit(True)))
                    t1y = t1.group_by("year").agg(pl.col("interest").sum().alias("t1_interest"), pl.col("stock").sum().alias("t1_stock")).sort("year")
                    for s, t in zip(sov.iter_rows(named=True), t1y.iter_rows(named=True)):
                        assert s["year"] == t["year"]
                        tot_int, tot_debt = s["interest_expense"] + t["t1_interest"], s["debt"] + t["t1_stock"]
                        r = tot_int / ((s["debt"] + t["t1_stock"]) if s["year"] == BASE_YEAR else tot_debt) * 100
                        crows.append(dict(country=cc, sov_case=sov_case, t1_case=t1_case, variant=variant, year=s["year"],
                                          sov_gg_interest_pct_gdp=sov_gg.filter(pl.col("year") == s["year"])["interest_pct_gdp"][0],
                                          sov_interest_pct_gdp=s["interest_pct_gdp"], t1_interest_pct_gdp=t["t1_interest"] / s["nominal_gdp"] * 100,
                                          total_interest_pct_gdp=tot_int / s["nominal_gdp"] * 100,
                                          sov_debt_pct_gdp=s["debt_pct_gdp"], t1_debt_pct_gdp=t["t1_stock"] / s["nominal_gdp"] * 100,
                                          total_debt_pct_gdp=tot_debt / s["nominal_gdp"] * 100,
                                          sov_avg_cost=s["avg_cost_pct"], blended_avg_cost=tot_int / tot_debt * 100 if s["year"] == BASE_YEAR else
                                          (s["avg_cost_pct"] * s["debt"] + (t["t1_interest"] / max(t["t1_stock"], 1e-9) * 100) * t["t1_stock"]) / tot_debt,
                                          ngdp_growth=sov_growth[(cc, sov_case)], central_primary_deficit=inp.primary_deficit_current - t1_bal[cc],
                                          t1_balance_share=t1_bal[cc]))
    cons = pl.DataFrame(crows)
    cons.write_csv(OUT / "CONSOLIDATED_paths.csv")

    # ---- console summary -----------------------------------------------------------------------------------------
    with pl.Config(tbl_rows=60, tbl_cols=20, float_precision=2, tbl_hide_dataframe_shape=True, tbl_hide_column_data_types=True, tbl_width_chars=220):
        print("== blocks: starting point ==")
        print(assumptions.filter(pl.col("case") == "base").select("country", "block", "fiscal", "stock_2026", "stock_pct_gdp", "cagr_2016_26", "start_cost_pct", "start_cost_vintage_check", "wam", "spread_pp", "growth_yr1", "growth_yr10"))
        print("== consolidated, fiscal blocks, sovereign market + tier-1 base: interest/GDP ==")
        c = cons.filter((pl.col("variant") == "fiscal") & (pl.col("sov_case") == "base") & (pl.col("t1_case") == "base") & pl.col("year").is_in([2026, 2031, 2036]))
        print(c.select("country", "year", "sov_gg_interest_pct_gdp", "sov_interest_pct_gdp", "t1_interest_pct_gdp", "total_interest_pct_gdp", "sov_debt_pct_gdp", "t1_debt_pct_gdp", "blended_avg_cost"))
        print("== tier-1 add in 2036 by joint case (fiscal blocks, matching sovereign curve) ==")
        print(cons.filter((pl.col("variant") == "fiscal") & (pl.col("year") == 2036) & (pl.col("sov_case") == pl.col("t1_case")))
              .pivot(on="t1_case", index="country", values="t1_interest_pct_gdp"))


if __name__ == "__main__":
    main()
