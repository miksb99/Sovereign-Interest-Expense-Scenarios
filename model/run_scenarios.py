#!/usr/bin/env python3
"""
run_scenarios.py -- run debt_model for every country and vintage: a lever grid plus four JOINT scenarios.

Every number is defined RELATIVE to the country's own starting point as read from its input file.

  base        market forwards; base growth = average of the 2016-25 nominal GDP CAGR and the latest year; primary
              deficit held (IMF general-government balance less modeled interest)
  bull        "AI boom, then disinflation", in two phases.  Phase 1 (2027-30) is the capex boom: the curve sits on market
              forwards, nominal growth runs base +1.0 everywhere (boom with inflation still 3-4%), the revenue harvest takes
              the primary balance to a surplus by 2030 and tier 1 keeps its middle settings.  Phase 2 (2031 on): the buildout is done, disinflation arrives and the
              central bank cuts; the curve glides linearly over 2031-32 to a TERMINAL curve (BULL_TERMINAL, 1Y/2Y/10Y/30Y)
              held as a level through 2036; growth falls back to base for the own-currency inflation targeters (US, UK,
              Canada, Australia: real +1.5 offset by inflation ~1.5) and stays base +1.0 for the euro members, Denmark and
              China (their bases carry little inflation to lose); the budget is the best case: the primary balance glides
              from today's level to a SURPLUS of at least BULL_SURPLUS % of GDP by 2030 (1.5 pt better where it is already in
              surplus) and stays there; France's terminal spread over Bunds tightens to ~100 bp at 10 years; tier 1
              moves to the tight spread and longer WAM.  Short-WAM issuers win in the back half (the US
              rolls ~57% of its stock within three years of the cuts); long-WAM issuers like the UK lock in phase-1 rates.
  bear        "inflation persists, higher for longer": real -1.5, inflation +1 -> nominal -0.5 pt; no cuts (front end
              +25 bp over market), term premium rebuilds scaled by the fiscal position (30Y +110 bp high-debt, +65 bp
              low-debt), France +50 / Italy +75 bp of spread loaded at 10Y and beyond; deficit worsens 1.5 pt by 2036
  repression  "inflation 3-4%, curve engineered down": inflation +1, real growth at base -> nominal +1.0 pt; the full cut
              c is held for the decade (negative real policy rate) and the long end is capped with term premium ~0, so
              the curve is flat (10Y ~ 1Y + 1.3, 30Y ~ 10Y + 0.3); the deficit is HELD because repression substitutes for
              consolidation.  It is a JOINT scenario, never crossed with the other levers.  For the euro members it is an
              ECB-bloc case, not a national choice (spreads compress: France ~+50, Italy ~+65 over Bunds); Australia gets
              a shallower cap (offshore ownership leaks into the exchange rate).

  Curves: the 2028 levels of the 1Y / 2Y / 10Y / 30Y points for bear and repression are tabulated per country in
  CURVES_2028, the bull's 2032 terminal levels in BULL_TERMINAL.  Every other tenor the engine prices takes the shift of
  the tabulated points (interpolated in maturity) applied to its own market forward, so bills, floaters and tier-1 tenors
  all move with the scenario.  Bear glides from today's spot to its 2028 level and then keeps that SHIFT OVER THE MARKET
  FORWARD PATH (so 'no cuts, +25 bp over market' stays +25 bp over market even where the forwards drift, e.g. France's
  1Y forward rises 0.8 pt between 2028 and 2036); repression is held at its 2028 LEVEL (a cap is an administered level);
  the bull terminal curve is held as a LEVEL from 2032.

  CHINA: growth 6 / 5 / 4 / 5 (bull / base / bear / repression); bull = the yield cap holds throughout (market forwards),
  base = developed-market steepening (long end +0.75 to +1.0 pt), bear = the cap fails (parallel +1.5 pt), repression =
  the cap holds (China already runs the repression curve); deficits as elsewhere.

  2016 vintage (back-test): the same scenarios from generic rules (see generic_levels) plus a 'realized' growth case;
  the report's back-test uses the market case only.

Outputs (per vintage, under outputs/<vintage>/):
  <CC>_interest_to_gdp.csv   the 3 x 3 x 3 lever grid (growth low/base/high x deficit improves/holds/worsens x curve
                             bull/market/bear) PLUS one joint repression row (growth 'repression', deficit 'holds', the
                             repression curve), one column per year
  ALL_interest_to_gdp.csv    the nine countries stacked
  ALL_detail_paths.csv       every year of every scenario with debt, avg cost, issuance etc. (for the report)
  ALL_assumptions.csv        the numeric path each named scenario resolved to, per country
"""
from __future__ import annotations
from pathlib import Path
import polars as pl
import debt_model as dm

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # repository root (model/ sits one level down)
DATA = ROOT / "data"
COUNTRIES = ["US", "CA", "UK", "DE", "FR", "IT", "CN", "DK", "AU"]
VINTAGES = [2026, 2016]

# ---- the four joint cases -----------------------------------------------------------------------------------------
CASES = ["bull", "base", "bear", "repression"]
CASE_LABEL = {"bull": "Bull: AI boom, then disinflation", "base": "Base: market forwards",
              "bear": "Bear: inflation persists, higher for longer", "repression": "Repression: inflation 3–4%, curve capped"}
CASE_GROWTH = {"bull": "high", "base": "base", "bear": "low", "repression": "repression"}      # growth scenario per case
CASE_DEFICIT = {"bull": "improves", "base": "holds", "bear": "worsens", "repression": "holds"}  # deficit scenario per case
GROWTH_DELTA = {"low": -0.5, "base": 0.0, "repression": 1.0}       # pp of nominal growth vs base (the bull path is two-phase, below)
DEFICIT_SHOCK = 1.5          # pp of GDP, reached by the final year (improves / worsens)
CUT_YEAR = 2                 # years after the base year at which the bear / repression curve is fully in place
BLOC_CONTINGENT = {"DE", "FR", "IT"}   # repression is an ECB decision for these, not a national option
CURVE_NAME = {"bull": "bull_ai_boom", "bear": "bear_higher_for_longer", "repression": "repression"}

# ---- the two-phase bull ---------------------------------------------------------------------------------------------
BULL_PHASE1_END = 4          # offset from the base year: 2027-2030 is the capex boom (market forwards, growth base +1, deficit held)
BULL_TERMINAL_FROM = 6       # offset: the terminal curve, tight tier-1 spread and long WAM are fully in place from 2032; 2031 blends
BULL_PHASE1_GROWTH = 1.0     # pp over base in phase 1, everywhere
BULL_PHASE2_GROWTH = {"US": 0.0, "UK": 0.0, "CA": 0.0, "AU": 0.0}   # pp over base in phase 2; every other country keeps +1.0
BULL_SURPLUS = 1.0           # best case: the primary balance becomes a SURPLUS of at least this % of GDP (deficits become surpluses);
#                            # countries already in surplus improve by DEFICIT_SHOCK instead
BULL_SURPLUS_BY = 4          # offset: the surplus is reached by 2030 (linear glide from today's balance) and held
BULL_TERMINAL = {            # 2032 terminal levels, % : 1Y / 2Y / 10Y / 30Y (France: 10Y spread over Bunds tightened to ~100 bp)
    "US": (2.0, 2.2, 3.0, 3.5), "CA": (1.5, 1.7, 2.5, 2.9), "UK": (1.8, 2.0, 2.9, 3.4), "AU": (1.8, 2.0, 2.9, 3.4),
    "DE": (1.0, 1.1, 1.8, 2.2), "FR": (1.2, 1.4, 2.8, 3.2), "IT": (1.2, 1.4, 2.9, 3.3), "DK": (0.8, 0.9, 1.6, 2.0)}


def bull_deficit_target(current: float) -> float:
    """Phase-2 primary balance the bull glides to by the final year (% of GDP, + = deficit)."""
    return min(current - DEFICIT_SHOCK, -BULL_SURPLUS)


def bull_phase2_weight(year: int, base_year: int) -> float:
    """0 in phase 1, 1 once the terminal regime is in place, linear in between (the 2031 blend year)."""
    off = year - base_year
    return min(1.0, max(0.0, (off - BULL_PHASE1_END) / (BULL_TERMINAL_FROM - BULL_PHASE1_END)))


# 2028 levels, % : 1Y / 2Y / 10Y / 30Y  (2026 vintage; China handled separately below)
ANCHOR_TENORS = ("1Y", "2Y", "10Y", "30Y")
CURVES_2028 = {
    "bear": {"US": (4.9, 5.0, 5.9, 6.5), "UK": (5.0, 5.0, 6.2, 6.9), "CA": (3.5, 3.7, 4.7, 4.9), "AU": (4.9, 5.0, 6.0, 6.4),
             "DE": (3.2, 3.3, 4.2, 4.4), "FR": (4.2, 4.5, 6.0, 6.6), "IT": (4.3, 4.4, 5.5, 6.3), "DK": (3.0, 3.2, 4.0, 4.3)},
    "repression": {"US": (1.9, 2.2, 3.3, 3.6), "UK": (1.9, 2.2, 3.4, 3.7), "CA": (1.1, 1.4, 2.4, 2.7), "AU": (2.0, 2.4, 3.7, 4.1),
                   "DE": (1.3, 1.4, 2.0, 2.2), "FR": (1.8, 1.9, 2.5, 2.7), "IT": (1.9, 2.0, 2.7, 2.9), "DK": (1.2, 1.3, 1.9, 2.1)},
}
# tenors that always get an explicit anchor (bucket price tenors and any extra tenors are added on top)
STD_TENORS = ["O/N", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "12Y", "15Y", "20Y", "25Y", "30Y"]
HIGH_DEBT = 60               # % of GDP; generic bear rule: 30Y term premium +110 bp above this, +65 bp below


def policy_cut(inp: dm.ModelInputs) -> float:
    """Size of a full easing cycle: half the current policy rate, floored at 25 bp and capped at 200 bp."""
    return min(2.0, max(0.25, 0.5 * inp.curves.spot(0.0)))


# ---- China is handled on its own terms (its curve sits at 1-2% and is administered) -------------------------------
CN_GROWTH = {"low": 4.0, "base": 5.0, "high": 6.0, "repression": 5.0}   # nominal GDP growth, % a year
CN_BEAR_SHIFT = 1.5                                                     # bear: the yield cap fails, parallel +1.5 pp (~2016 levels)
CN_BASE_STEEPEN = {"O/N": 0.0, "1Y": 0.0, "2Y": 0.1, "3Y": 0.2, "5Y": 0.4, "7Y": 0.55, "10Y": 0.75, "20Y": 1.0, "30Y": 1.0}
#                                                                       # base: China starts to price like a developed market
#                                                                       # bull and repression: the cap holds (= market forwards)


def _interp(x: float, pts: list[tuple[float, float]]) -> float:
    """Piecewise-linear in x through sorted (x, y) points, flat beyond the ends."""
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def _labels(inp: dm.ModelInputs, extra_tenors=()) -> set[str]:
    return set(STD_TENORS) | {b.price_tenor for b in inp.buckets} | set(extra_tenors)


def anchors_from_levels(inp: dm.ModelInputs, levels: dict[str, float], extra_tenors=(), hold: str = "spread") -> dict:
    """{tenor: level in year base+CUT_YEAR} for a few tenors -> absolute anchors for EVERY tenor the engine prices.
    Un-tabulated tenors take the shift (level minus market forward) of the tabulated ones, interpolated in maturity.
    hold = "spread": after year CUT_YEAR the curve keeps that shift OVER THE MARKET FORWARD PATH (a 'no cuts, +25 bp over
                     market' story stays +25 bp over market all decade even where the forwards drift)
    hold = "level" : after year CUT_YEAR the curve is held at the CUT_YEAR level (an administered cap)."""
    y0 = inp.base_year + CUT_YEAR
    shift_pts = sorted((dm.parse_tenor(t), lv - inp.curves.market_rate(t, y0)) for t, lv in levels.items())
    spec = {}
    for lab in _labels(inp, extra_tenors) | set(levels):
        sh = (levels[lab] - inp.curves.market_rate(lab, y0)) if lab in levels else _interp(dm.parse_tenor(lab), shift_pts)
        for y in (inp.years if hold == "spread" else [y0]):
            if y >= y0:
                spec[(lab, y - inp.base_year)] = inp.curves.market_rate(lab, y) + sh
    return spec


def bull_anchors(inp: dm.ModelInputs, terminal: dict[str, float], extra_tenors=()) -> dict:
    """Two-phase bull curve: market forwards through phase 1, a linear glide to the terminal levels (held as a level) by
    BULL_TERMINAL_FROM.  Anchors are written for every year so the engine reproduces the market path exactly in phase 1."""
    yT = inp.base_year + BULL_TERMINAL_FROM
    shift_pts = sorted((dm.parse_tenor(t), lv - inp.curves.market_rate(t, yT)) for t, lv in terminal.items())
    spec = {}
    for lab in _labels(inp, extra_tenors) | set(terminal):
        term = terminal[lab] if lab in terminal else inp.curves.market_rate(lab, yT) + _interp(dm.parse_tenor(lab), shift_pts)
        for y in inp.years:
            off = y - inp.base_year
            if off <= BULL_PHASE1_END:
                spec[(lab, off)] = inp.curves.market_rate(lab, y)
            elif off >= BULL_TERMINAL_FROM:
                spec[(lab, off)] = term
    return spec


def generic_levels(inp: dm.ModelInputs, case: str) -> dict[str, float]:
    """Rule-based levels used where no table exists (the 2016 vintage): the same stories as CURVES_2028 / BULL_TERMINAL."""
    y = inp.base_year + CUT_YEAR
    m = {t: inp.curves.market_rate(t, y) for t in ANCHOR_TENORS}
    c = policy_cut(inp)
    cc = inp.meta.get("country_code")
    if case == "bull":                                   # terminal curve after the cuts: policy ~1 pt below today's, flat-ish curve
        one = max(inp.curves.spot(0.0) - max(c, 1.0), -0.75)
        return {"1Y": one, "2Y": one + 0.2, "10Y": one + 1.0, "30Y": one + 1.5}
    if case == "bear":                                   # no cuts, term premium rebuilds with the fiscal position
        euro = cc in BLOC_CONTINGENT
        tp30 = 0.65 if (euro or inp.debt0 / inp.gdp0 * 100 < HIGH_DEBT) else 1.10
        sp = {"FR": 0.50, "IT": 0.75}.get(cc, 0.0)
        return {"1Y": m["1Y"] + 0.25, "2Y": m["2Y"] + 0.40, "10Y": m["10Y"] + 0.7 * tp30 + sp, "30Y": m["30Y"] + tp30 + sp}
    one = inp.curves.spot(0.0) - c                       # repression: full cut held, flat capped curve
    return {"1Y": one, "2Y": one + 0.3, "10Y": one + 1.3, "30Y": one + 1.6}


def curve_scenarios(inp: dm.ModelInputs, vintage: int = 2026, extra_tenors=()) -> dict:
    """Named rate-scenario specs for debt_model (the market curve is always added by the engine)."""
    cc = inp.meta.get("country_code")
    labels = _labels(inp, extra_tenors)
    y0 = inp.base_year + CUT_YEAR
    if cc == "CN":                                       # shifts over the market path, reached by CUT_YEAR and kept
        pts = sorted((dm.parse_tenor(t), k) for t, k in CN_BASE_STEEPEN.items())
        steep = {t: inp.curves.market_rate(t, y0) + _interp(dm.parse_tenor(t), pts) for t in labels}
        fails = {t: inp.curves.market_rate(t, y0) + CN_BEAR_SHIFT for t in labels}
        return {"cn_dm_steepener": anchors_from_levels(inp, steep, extra_tenors, "spread"),
                "cn_cap_fails_parallel": anchors_from_levels(inp, fails, extra_tenors, "spread")}
    out = {}
    for case in ("bear", "repression"):
        if vintage == 2026 and cc in CURVES_2028[case]:
            levels = dict(zip(ANCHOR_TENORS, CURVES_2028[case][cc]))
        else:
            levels = generic_levels(inp, case)
        out[CURVE_NAME[case]] = anchors_from_levels(inp, levels, extra_tenors, "level" if case == "repression" else "spread")
    terminal = dict(zip(ANCHOR_TENORS, BULL_TERMINAL[cc])) if (vintage == 2026 and cc in BULL_TERMINAL) else generic_levels(inp, "bull")
    out[CURVE_NAME["bull"]] = bull_anchors(inp, terminal, extra_tenors)
    return out


def curve_roles(inp: dm.ModelInputs) -> dict:
    """Which named rate scenario plays each case for this country."""
    if inp.meta.get("country_code") == "CN":
        return {"bull": "market", "base": "cn_dm_steepener", "bear": "cn_cap_fails_parallel", "repression": "market"}
    return {"bull": CURVE_NAME["bull"], "base": "market", "bear": CURVE_NAME["bear"], "repression": CURVE_NAME["repression"]}


def settings_for(inp: dm.ModelInputs, vintage: int, extra_tenors=()) -> dict:
    base = inp.base_year
    latest = inp.history["ngdp_growth_pct"][base]
    trend = inp.history["ngdp_growth_trend_pct"][base]
    cc = inp.meta.get("country_code")
    if vintage == 2026 and cc == "CN":
        growth = dict(CN_GROWTH)
        growth["high"] = {1: CN_GROWTH["high"], 10: CN_GROWTH["high"]}
    else:
        g_base = (latest + trend) / 2 if vintage == 2026 else latest          # 2016: what was observable then
        growth = {k: g_base + d for k, d in GROWTH_DELTA.items()}
        g1, g2 = g_base + BULL_PHASE1_GROWTH, g_base + BULL_PHASE2_GROWTH.get(cc, BULL_PHASE1_GROWTH)
        growth["high"] = {1: g1, BULL_PHASE1_END: g1, BULL_PHASE1_END + 1: g2, 10: g2}   # two-phase bull path
        if vintage != 2026:
            growth["realized"] = trend
    # 'improves' is the bull's budget: the boom's revenue harvest takes the primary balance to a surplus by BULL_SURPLUS_BY (2030) and
    # holds it there.  Resolved against inp.primary_deficit_current at call time (the consolidated scripts set the central figure first).
    tgt = bull_deficit_target(inp.primary_deficit_current)
    deficit = {"improves": {BULL_SURPLUS_BY: tgt, 10: tgt}, "holds": None, "worsens": {10: f"+{DEFICIT_SHOCK}"}}
    return dict(growth=growth, deficit=deficit, mix=None, rates=curve_scenarios(inp, vintage, extra_tenors), cut=policy_cut(inp))


# ---- real / inflation split of the growth assumptions (presentation only: the engine runs on nominal growth) -----------------
# base real growth = average of the 2016-25 real GDP CAGR and the latest year (World Bank constant-LCU GDP, 'real_gdp_growth_*'
# history rows); base inflation = base nominal less base real (the GDP deflator).  Each case adds (real, inflation) points that sum
# to the nominal delta it already uses, so the split changes nothing in the results.
SPLIT = {"base": (0.0, 0.0), "low": (-1.5, 1.0), "repression": (0.0, 1.0)}   # bear: real -1.5, inflation +1; repression: inflation +1, real at base
BULL_SPLIT_PHASE1 = (1.0, 0.0)                                               # capex boom, inflation still 3-4%
BULL_SPLIT_PHASE2 = {"own_ccy": (1.5, -1.5), "other": (1.5, -0.5)}           # US/UK/CA/AU: real +1.5 offset by disinflation; euro, DK keep more of it
CN_SPLIT = {"base": (0.0, 0.0), "high": (1.0, 0.0), "low": (-1.5, 0.5), "repression": (0.0, 0.0)}


def growth_split(inp: dm.ModelInputs, vintage: int, growth_paths: dict) -> dict | None:
    """{growth scenario: {year: (real %, inflation %)}} consistent with the nominal paths; None if the input has no real-growth rows."""
    base = inp.base_year
    if "real_gdp_growth_pct" not in inp.history or "real_gdp_growth_trend_pct" not in inp.history:
        return None
    r_latest, r_trend = inp.history["real_gdp_growth_pct"][base], inp.history["real_gdp_growth_trend_pct"][base]
    base_real = (r_latest + r_trend) / 2 if vintage == 2026 else r_latest
    base_nom = growth_paths["base"][inp.years[0]]
    base_infl = base_nom - base_real
    cc = inp.meta.get("country_code")
    out = {}
    for name, path in growth_paths.items():
        out[name] = {}
        for y, g in path.items():
            if cc == "CN" and vintage == 2026:
                dr, di = CN_SPLIT.get(name, (g - base_nom, 0.0))
            elif name == "high":
                dr, di = BULL_SPLIT_PHASE1 if y - base <= BULL_PHASE1_END else BULL_SPLIT_PHASE2["own_ccy" if cc in BULL_PHASE2_GROWTH else "other"]
            else:
                dr, di = SPLIT.get(name, (g - base_nom, 0.0))               # e.g. the 2016 'realized' case: all real
            assert abs((dr + di) - (g - base_nom)) < 1e-6, (cc, name, y, dr, di, g - base_nom)
            out[name][y] = (base_real + dr, base_infl + di)
    return out


def split_runs(inp: dm.ModelInputs, scen: dm.Scenarios) -> tuple[dm.Scenarios, dm.Scenarios]:
    """The lever grid (growth low/base/high[/realized] x deficit x curve bull/base/bear) and the single joint repression cell."""
    roles = curve_roles(inp)
    grid = dm.Scenarios(growth={k: v for k, v in scen.growth.items() if k != "repression"}, deficit=scen.deficit, issuance=scen.issuance,
                        rates={n: scen.rates[n] for n in dict.fromkeys([roles["base"], roles["bull"], roles["bear"], "market"])}, notes=scen.notes)
    rep = dm.Scenarios(growth={"repression": scen.growth["repression"]}, deficit={"holds": scen.deficit["holds"]}, issuance=scen.issuance,
                       rates={roles["repression"]: scen.rates[roles["repression"]]}, notes=[])
    return grid, rep


def main() -> None:
    for vintage in VINTAGES:
        out_dir = ROOT / "outputs" / str(vintage)
        out_dir.mkdir(parents=True, exist_ok=True)
        wide, detail, assumptions, summary = [], [], [], []
        for cc in COUNTRIES:
            inp = dm.load_inputs(DATA / "inputs" / str(vintage) / f"{cc}_debt_inputs.csv")
            if inp.warnings:
                print(f"{vintage} {cc}: WARNING {inp.warnings}")
            st = settings_for(inp, vintage)
            scen = dm.resolve_scenarios(inp, st["growth"], st["deficit"], st["mix"], st["rates"])
            grid, rep = split_runs(inp, scen)
            out, outr = dm.run_all(inp, grid), dm.run_all(inp, rep)
            w = pl.concat([out.interest_to_gdp, outr.interest_to_gdp], how="vertical_relaxed")
            w.write_csv(out_dir / f"{cc}_interest_to_gdp.csv")
            wide.append(w)
            detail.append(pl.concat([out.paths, outr.paths], how="vertical_relaxed"))
            for kind, d in (("growth", scen.growth), ("deficit", scen.deficit)):
                for name, path in d.items():
                    assumptions.append(dict(vintage=vintage, country=cc, kind=kind, scenario=name,
                                            **{str(y): v for y, v in path.items()}))
            split = growth_split(inp, vintage, scen.growth)
            if split:
                for name, path in split.items():
                    assumptions.append(dict(vintage=vintage, country=cc, kind="growth_real", scenario=name, **{str(y): v[0] for y, v in path.items()}))
                    assumptions.append(dict(vintage=vintage, country=cc, kind="growth_inflation", scenario=name, **{str(y): v[1] for y, v in path.items()}))
            for name, mat in scen.rates.items():
                for ten in ("O/N", "1Y", "2Y", "10Y", "30Y"):
                    assumptions.append(dict(vintage=vintage, country=cc, kind=f"rate_{ten}", scenario=name,
                                            **{str(y): mat[(ten, y)] for y in inp.years}))
            assumptions.append(dict(vintage=vintage, country=cc, kind="policy_cut_pp", scenario="c", **{str(y): st["cut"] for y in inp.years}))
            roles = curve_roles(inp)
            yH = str(inp.years[-1])
            rec = dict(country=cc)
            for case in CASES:
                rec[case] = w.filter((pl.col("rate_scenario") == roles[case]) & (pl.col("deficit_scenario") == CASE_DEFICIT[case])
                                     & (pl.col("growth_scenario") == CASE_GROWTH[case]))[yH][0]
            summary.append(rec)
            print(f"{vintage} {cc}: {w.height} scenarios; base growth {scen.growth['base'][inp.years[0]]:.2f}%, "
                  f"primary deficit {inp.primary_deficit_current:+.2f}% GDP, int/GDP {out.paths['interest_pct_gdp'][0]:.2f}%")
        pl.concat(wide, how="vertical_relaxed").write_csv(out_dir / "ALL_interest_to_gdp.csv")
        pl.concat(detail, how="vertical_relaxed").write_csv(out_dir / "ALL_detail_paths.csv")
        pl.DataFrame(assumptions).write_csv(out_dir / "ALL_assumptions.csv")
        with pl.Config(float_precision=2, tbl_hide_dataframe_shape=True, tbl_hide_column_data_types=True):
            print(f"{vintage}: sovereign-only interest/GDP in the final year by joint case (GG deficit)")
            print(pl.DataFrame(summary))
        print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
