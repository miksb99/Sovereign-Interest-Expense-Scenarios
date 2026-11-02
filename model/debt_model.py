#!/usr/bin/env python3
"""
debt_model.py  --  sovereign interest-expense scenario model (polars)
=====================================================================

Projects a government's interest expense as a share of GDP under a grid of
assumptions.  The DATA for a country lives in a long-format input CSV (one file per
country, same layout for all); the ASSUMPTIONS live in the USER SETTINGS block right
below this docstring.  Output is one CSV: one row per scenario combination, one
column per year, values = interest expense / nominal GDP in percent.

    python debt_model.py                      # runs INPUT_CSV from the settings block
    python debt_model.py some_country.csv     # or name the file on the command line

-------------------------------------------------------------------------------
HOW THE PROJECTION WORKS
-------------------------------------------------------------------------------
Start from today's stock of government debt, its average interest cost, and the
schedule on which the EXISTING bonds mature (the "maturity ladder").  Then roll the
debt forward one fiscal year at a time:

  1. Everything that matures this year has to be refinanced: (a) the bonds in the
     measured maturity ladder, plus (b) the bonds the model itself issued in earlier
     projection years that are now coming due (bills issued last year, 2y notes
     issued two years ago, ...).  These are tracked as "cohorts".
  2. On top of refinancing, the government borrows the PRIMARY deficit (spending
     ex-interest minus revenue) and LAST year's interest bill.  Interest is lagged
     one year on purpose: it avoids a circular reference.
  3. Gross issuance = (1) + (2).  It is split across tenors using the issuance mix
     and each slice is priced at that tenor's rate for that year.  Each slice is a
     new cohort that matures `maturity_years` later at the rate it was issued at.
  4. The average cost of the stock updates with a stock/flow identity:
        new_cost = (old_debt*old_cost - maturing*cost_of_maturing
                    + issued*cost_of_new) / new_debt
  5. Interest expense = average cost x average debt over the year.
  6. Interest / nominal GDP is the output.

The run is a grid: growth scenarios x deficit scenarios x issuance-mix scenarios x
rate scenarios.  The market-implied curve is always one of the rate scenarios.

-------------------------------------------------------------------------------
HOW THE MARKET-IMPLIED RATE PATH IS BUILT
-------------------------------------------------------------------------------
Inputs: spot par yields y(m), today's implied term premium tp(m), and the static
term premium stp(m) assumed going forward.
  forward par yield    f(h, m)   = [ y(h+m)*(h+m) - y(h)*h ] / m
  forward term premium ftp(h, m) = [ tp(h+m)*(h+m) - tp(h)*h ] / m
  assumed rate         r(h, m)   = f(h, m) - ftp(h, m) + stp(m)
  overnight            r_on(h)   = f(h, 1) - ftp(h, 1) - on_wedge   (pure expectations)
Curves are linearly interpolated between the tenors supplied and held flat beyond.

-------------------------------------------------------------------------------
UNITS:  money in whatever unit the input CSV uses (must be consistent within a
file); rates in PERCENT; shares as FRACTIONS; growth and deficit in PERCENT.
"""

from __future__ import annotations

# =============================================================================
# =============================================================================
#   USER SETTINGS  --  the only block you normally edit
# =============================================================================
# =============================================================================

# ---- 1. Which country file to run -------------------------------------------
INPUT_CSV = "../data/inputs/2026/US_debt_inputs.csv"   # relative to this script's folder, or an absolute path
OUTPUT_DIR = None                  # None -> outputs/standalone/ at the repository root
HORIZON_YEARS = None               # None -> the value in the input file's meta block
DETAIL_OUTPUT = False              # True -> also write the full year-by-year paths and rate matrices

# ---- 2. Assumptions -----------------------------------------------------------
# Each assumption accepts None = "zeroed out", meaning the model uses the CURRENT
# value read from the input file:
#     NGDP_GROWTH             -> last historical year's nominal GDP growth, held flat
#     PRIMARY_DEFICIT_PCT_GDP -> base-year primary deficit / GDP, held flat
#     ISSUANCE_MIX            -> current issuance composition
#     RATE_SCENARIOS          -> market-implied forward curve only
#
# Conventions that make the same settings work for every country file:
#   * year keys may be calendar years (2029) or OFFSETS from the base year (3 = base+3)
#   * a value written as a signed STRING is RELATIVE to the current value:
#       "+2"   = current + 2 percentage points     "-1.5" = current - 1.5 points
#     (for rate anchors: relative to that tenor's market rate in the base year)
#   * a plain number is an absolute level in percent

# NGDP_GROWTH and PRIMARY_DEFICIT_PCT_GDP accept any of:
#     None                            current value, flat
#     4.0                             4.0 % every year;   "-1" = current - 1 pt every year
#     {3: 3.0}                        glide from the current value to 3.0 % by base+3, flat after
#     {1: 4.3, 2: 4.1, 3: 3.9}        explicit path: linear between points, flat after the last
#     {"low": 3, "high": "+2"}        several NAMED scenarios; each entry may be any form above
#                                     (None inside a dict = current value)
NGDP_GROWTH = {"low": 3, "mid": 6, "high": 12}
PRIMARY_DEFICIT_PCT_GDP = {
    "improves": {10: "-1.8"},   # glide from current to current - 1.8 pts of GDP by base+10
    "holds": None,              # current primary deficit, flat
    "worsens": {10: "+1.7"},    # glide to current + 1.7 pts of GDP by base+10
}

# ISSUANCE_MIX accepts:
#     None                                     current composition for every year
#     {"Bills": 0.50, "2Y": 0.08, ...}         one alternative composition (bucket names as in the
#                                              input file; buckets left out get 0; should sum to 1)
#     {"more_bills": {...}, "term_out": {...}} several NAMED compositions
ISSUANCE_MIX = None

# RATE_SCENARIOS: the market-implied curve is ALWAYS run as scenario "market".  Extras:
#     None                        market only
#     1.0                         one extra scenario: market +1.00 pp on every tenor, every year
#     {"name": spec, ...}         several, where each spec is one of
#          0.5                                parallel shift in pp versus market, every year
#          {"O/N": 2.0, "1Y": "-2"}           level reached in the FIRST forecast year, flat after
#          {("1Y", 1): 2.9, ("1Y", 3): 2.0}   anchors (tenor, year): glide from today's market rate
#                                             to the first anchor, linear between anchors, flat
#                                             after the last; tenors not listed stay at market
RATE_SCENARIOS = {
    # front end 200bp below today's level within two years, long end stays at market forwards
    "front_end_cut": {("O/N", 2): "-2", ("1Y", 2): "-2"},
    # whole curve lower within two years: front end -2 pts, belly -1.5, long end -1.25
    "curve_lower": {("O/N", 2): "-2", ("1Y", 2): "-2", ("2Y", 2): "-1.9", ("3Y", 2): "-1.8",
                    ("5Y", 2): "-1.5", ("7Y", 2): "-1.4", ("10Y", 2): "-1.25", ("20Y", 2): "-1.25",
                    ("30Y", 2): "-1.25"},
}

# =============================================================================
#   END OF USER SETTINGS  --  engine below
# =============================================================================

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

# =============================================================================
# 0.  Small helpers
# =============================================================================

OVERNIGHT_LABELS = {"O/N", "ON", "OVERNIGHT"}
Number = (int, float)


def is_overnight(label: str) -> bool:
    return label.strip().upper() in OVERNIGHT_LABELS


def parse_tenor(label: str) -> float:
    """Tenor label -> maturity in YEARS.  'O/N'->0, '3M'->0.25, '1Y'->1, '30Y'->30, '13W'->0.25."""
    s = str(label).strip().upper()
    if s in OVERNIGHT_LABELS:
        return 0.0
    try:
        if s.endswith("Y"):
            return float(s[:-1])
        if s.endswith("M"):
            return float(s[:-1]) / 12.0
        if s.endswith("W"):
            return float(s[:-1]) / 52.0
        return float(s)
    except ValueError as exc:
        raise ValueError(f"Cannot parse tenor label '{label}' (use e.g. 'O/N', '3M', '2Y')") from exc


def _f(x) -> float | None:
    """String -> float, blanks -> None."""
    if x is None:
        return None
    x = str(x).strip()
    return float(x) if x != "" else None


def _year(key, base_year: int) -> int:
    """Settings may use calendar years (2029) or offsets from the base year (3)."""
    k = int(key)
    return base_year + k if k < 1000 else k


def _level(value, current: float | None, label: str) -> float:
    """A number is an absolute level; a signed string ('+2', '-1.5') is relative to `current`."""
    if isinstance(value, str):
        s = value.strip()
        if not s or s[0] not in "+-":
            raise ValueError(f"{label}: relative values must be signed strings like '+2' or '-1.5', got {value!r}")
        if current is None:
            raise ValueError(f"{label}: relative value {value!r} needs a current value, which the input file does not provide")
        return current + float(s)
    return float(value)


def _interp_path(knots: list[tuple[int, float]], years: list[int]) -> dict[int, float]:
    """Piecewise-linear path through (year, value) knots; flat before the first and after the last."""
    knots = sorted(knots)
    out: dict[int, float] = {}
    for y in years:
        if y <= knots[0][0]:
            out[y] = knots[0][1]
        elif y >= knots[-1][0]:
            out[y] = knots[-1][1]
        else:
            for (y0, v0), (y1, v1) in zip(knots[:-1], knots[1:]):
                if y0 <= y <= y1:
                    out[y] = v0 + (v1 - v0) * (y - y0) / (y1 - y0)
                    break
    return out


# =============================================================================
# 1.  Yield-curve machinery
# =============================================================================


class Curve:
    """Piecewise-linear curve over tenor (years), flat beyond the end points."""

    def __init__(self, points: dict[str, float]):
        if not points:
            raise ValueError("Curve needs at least one point")
        knots = sorted((parse_tenor(k), float(v)) for k, v in points.items())
        self.t = [k[0] for k in knots]
        self.v = [k[1] for k in knots]

    def __call__(self, t: float) -> float:
        if t <= self.t[0]:
            return self.v[0]
        if t >= self.t[-1]:
            return self.v[-1]
        for i in range(1, len(self.t)):
            if t <= self.t[i]:
                w = (t - self.t[i - 1]) / (self.t[i] - self.t[i - 1])
                return self.v[i - 1] + w * (self.v[i] - self.v[i - 1])
        return self.v[-1]


def forward_par(curve: Curve, h: float, m: float) -> float:
    """f(h, m) = [y(h+m)(h+m) - y(h)h] / m.  With h = 0 this is just the spot rate y(m)."""
    if m <= 0:
        raise ValueError("forward_par needs a positive tenor m")
    return (curve(h + m) * (h + m) - curve(h) * h) / m


@dataclass
class CurveSet:
    spot: Curve
    implied_tp: Curve
    static_tp: Curve
    on_wedge: float
    base_year: int

    def market_rate(self, tenor_label: str, year: int) -> float:
        """Market-implied rate (%) for `tenor_label` issued in `year`."""
        h = year - self.base_year
        if is_overnight(tenor_label):
            return forward_par(self.spot, h, 1.0) - forward_par(self.implied_tp, h, 1.0) - self.on_wedge
        m = parse_tenor(tenor_label)
        return forward_par(self.spot, h, m) - forward_par(self.implied_tp, h, m) + self.static_tp(m)


# =============================================================================
# 2.  Input container + CSV loader   (DATA only -- assumptions come from the settings block)
# =============================================================================


@dataclass
class Bucket:
    name: str
    maturity_years: int            # projection years until a cohort of this bucket rolls
    price_tenor: str               # curve tenor that prices it ('1Y', 'O/N', '5Y', ...)
    in_ladder: bool                # True if the base-year stock is already in the maturity ladder
    base_outstanding: float | None = None   # explicit base-year stock for buckets not in the ladder


@dataclass
class ModelInputs:
    meta: dict[str, str]
    base_year: int
    horizon: int
    years: list[int]                            # base_year+1 .. base_year+horizon
    debt0: float
    cost0: float
    gdp0: float
    issuance0: float | None
    history: dict[str, dict[int, float]]
    buckets: list[Bucket]
    mix: dict[tuple[str, int], float]           # CURRENT composition, (bucket, year) incl. base year
    ladder: dict[int, tuple[float, float]]      # year -> (amount maturing, avg coupon %)
    curves: CurveSet
    ngdp_growth_current: float | None           # last historical nominal growth, %
    primary_deficit_current: float | None       # base-year primary deficit, % of GDP
    warnings: list[str] = field(default_factory=list)


def _section(df: pl.DataFrame, name: str) -> pl.DataFrame:
    return df.filter(pl.col("section") == name)


def _fill_path(rows: pl.DataFrame, years: list[int], label: str) -> dict[int, float]:
    """(period, value) rows -> complete {year: value}; blank period = default, forward-filled."""
    default = None
    specific: dict[int, float] = {}
    for period, value in rows.select("period", "value").iter_rows():
        v = _f(value)
        if v is None:
            continue
        if period is None or str(period).strip() == "":
            default = v
        else:
            specific[int(float(period))] = v
    path: dict[int, float] = {}
    last = default
    for y in years:
        if y in specific:
            last = specific[y]
        if last is None:
            raise ValueError(f"{label}: no value for {y} and no default (blank-period) row")
        path[y] = last
    return path


def load_inputs(path: str | Path, horizon_override: int | None = None) -> ModelInputs:
    """Read a country's long-format input CSV and return a validated ModelInputs object."""
    path = Path(path)
    raw = pl.read_csv(path, comment_prefix="#", infer_schema=False, truncate_ragged_lines=True)
    raw = raw.rename({c: c.strip().lstrip("﻿").lower() for c in raw.columns})
    needed = {"section", "item", "sub_item", "period", "value"}
    if needed - set(raw.columns):
        raise ValueError(f"{path.name}: missing column(s) {sorted(needed - set(raw.columns))}; "
                         f"expected header 'section,item,sub_item,period,value,notes'")
    raw = (
        raw.with_columns([pl.col(c).str.strip_chars() for c in ["section", "item", "sub_item", "period", "value"]])
        .filter(pl.col("section").is_not_null() & (pl.col("section") != ""))
    )
    warnings: list[str] = []

    # ---- meta ------------------------------------------------------------------
    meta = {k: v for k, v in _section(raw, "meta").select("item", "value").iter_rows()}
    base_year = int(float(meta["base_year"]))
    horizon = int(horizon_override or float(meta.get("horizon_years", 10)))
    years = [base_year + i for i in range(1, horizon + 1)]

    # ---- history -----------------------------------------------------------------
    history: dict[str, dict[int, float]] = {}
    for item, period, value in _section(raw, "history").select("item", "period", "value").iter_rows():
        v = _f(value)
        if v is None or period in (None, ""):
            continue
        history.setdefault(item, {})[int(float(period))] = v

    def hist(item: str, year: int) -> float | None:
        return history.get(item, {}).get(year)

    def required(item: str) -> float:
        v = hist(item, base_year)
        if v is None:
            raise ValueError(f"history: '{item}' is required for base year {base_year}")
        return v

    debt0, cost0, gdp0 = required("debt_held_by_public"), required("avg_cost_pct"), required("nominal_gdp")
    issuance0 = hist("gross_issuance", base_year)

    # "current" values used whenever a setting is None or relative
    ngdp_growth_current = hist("ngdp_growth_pct", base_year)
    if ngdp_growth_current is None and hist("nominal_gdp", base_year - 1):
        ngdp_growth_current = (gdp0 / hist("nominal_gdp", base_year - 1) - 1.0) * 100.0
    primary_deficit_current = hist("primary_deficit_pct_gdp", base_year)
    if primary_deficit_current is None and hist("fiscal_deficit", base_year) is not None \
            and hist("net_interest", base_year) is not None:
        primary_deficit_current = (hist("fiscal_deficit", base_year) - hist("net_interest", base_year)) / gdp0 * 100.0

    # ---- buckets ----------------------------------------------------------------------
    bdf = _section(raw, "bucket")
    buckets: list[Bucket] = []
    for name in bdf.get_column("item").unique(maintain_order=True).to_list():
        attrs = {s: v for s, v in bdf.filter(pl.col("item") == name).select("sub_item", "value").iter_rows()}
        try:
            buckets.append(Bucket(
                name=name, maturity_years=int(float(attrs["maturity_years"])), price_tenor=attrs["price_tenor"],
                in_ladder=bool(int(float(attrs.get("in_ladder", "1")))),
                base_outstanding=_f(attrs.get("base_outstanding")),
            ))
        except KeyError as exc:
            raise ValueError(f"bucket '{name}' is missing attribute {exc}") from exc
    if not buckets:
        raise ValueError("No 'bucket' rows found")

    # ---- current issuance mix ------------------------------------------------------------
    mdf = _section(raw, "issuance_mix")
    mix: dict[tuple[str, int], float] = {}
    all_years = [base_year] + years
    for b in buckets:
        rows = mdf.filter(pl.col("item") == b.name)
        if rows.height == 0:
            raise ValueError(f"issuance_mix: no share rows for bucket '{b.name}'")
        for y, s in _fill_path(rows, all_years, f"issuance_mix[{b.name}]").items():
            mix[(b.name, y)] = s
    tot = sum(mix[(b.name, base_year)] for b in buckets)
    if abs(tot - 1.0) > 1e-6:
        warnings.append(f"issuance_mix sums to {tot:.4f}, not 1.0: cohort amounts use the raw shares "
                        f"({1-tot:+.2%} of issuance never gets a maturity) while the new-issue cost is normalised.")

    # ---- maturity ladder -------------------------------------------------------------------
    ldf = _section(raw, "maturity_ladder")
    amt = {int(float(p)): _f(v) for i, p, v in ldf.select("item", "period", "value").iter_rows()
           if i == "amount" and p not in (None, "") and _f(v) is not None}
    cpn = {int(float(p)): _f(v) for i, p, v in ldf.select("item", "period", "value").iter_rows()
           if i == "coupon_pct" and p not in (None, "") and _f(v) is not None}
    ladder: dict[int, tuple[float, float]] = {}
    for y in years:
        if y not in amt or y not in cpn:
            raise ValueError(f"maturity_ladder: need both 'amount' and 'coupon_pct' for {y}")
        ladder[y] = (amt[y], cpn[y])

    # ---- curves -----------------------------------------------------------------------------
    def curve_from(section: str) -> Curve:
        pts = {k: _f(v) for k, v in _section(raw, section).select("item", "value").iter_rows() if _f(v) is not None}
        if not pts:
            raise ValueError(f"section '{section}' has no numeric rows")
        return Curve(pts)

    cparams = {k: _f(v) for k, v in _section(raw, "curve_param").select("item", "value").iter_rows()}
    curves = CurveSet(spot=curve_from("spot_curve"), implied_tp=curve_from("implied_tp"),
                      static_tp=curve_from("static_tp"), on_wedge=cparams.get("on_wedge") or 0.0,
                      base_year=base_year)

    legacy = {"growth_scenario", "deficit_scenario", "rate_scenario"} & set(raw.get_column("section").unique().to_list())
    if legacy:
        warnings.append(f"input sections {sorted(legacy)} are ignored: assumptions are set at the top of debt_model.py.")

    return ModelInputs(meta=meta, base_year=base_year, horizon=horizon, years=years, debt0=debt0, cost0=cost0,
                       gdp0=gdp0, issuance0=issuance0, history=history, buckets=buckets, mix=mix, ladder=ladder,
                       curves=curves, ngdp_growth_current=ngdp_growth_current,
                       primary_deficit_current=primary_deficit_current, warnings=warnings)


# =============================================================================
# 3.  Rate matrix (tenor x year) for a scenario
# =============================================================================

RateMatrix = dict[tuple[str, int], float]     # (tenor_label, year) -> rate in %


def build_rate_matrix(inp: ModelInputs, spec=None, extra_tenors: list[str] | None = None) -> RateMatrix:
    """Market-implied matrix with a scenario spec layered on top (formats: see USER SETTINGS)."""
    shift, raw_anchors = 0.0, {}
    if isinstance(spec, Number):
        shift = float(spec)
    elif isinstance(spec, dict):
        for k, v in spec.items():
            if isinstance(k, tuple):
                tenor, y = k[0], _year(k[1], inp.base_year)
            else:
                tenor, y = str(k), inp.base_year + 1           # bare tenor = move in the first forecast year
            if y <= inp.base_year:
                raise ValueError(f"rate anchor {k}: year must be after base year {inp.base_year}")
            raw_anchors[(tenor, y)] = v
    elif spec is not None:
        raise TypeError(f"Unsupported rate scenario spec: {spec!r}")

    labels = {b.price_tenor for b in inp.buckets} | {t for (t, _) in raw_anchors} | set(extra_tenors or [])
    all_years = [inp.base_year] + inp.years
    mat: RateMatrix = {}
    for lab in sorted(labels, key=parse_tenor):
        market = {y: inp.curves.market_rate(lab, y) for y in all_years}
        today = market[inp.base_year]
        pts = sorted((y, _level(v, today, f"rate anchor ({lab}, {y})")) for (t, y), v in raw_anchors.items() if t == lab)
        if pts:    # glide from today's market rate to the first anchor, linear between, flat after
            path = _interp_path([(inp.base_year, today)] + pts, all_years)
        else:
            path = {y: market[y] + (shift if y > inp.base_year else 0.0) for y in all_years}
        for y in all_years:
            mat[(lab, y)] = path[y]
    return mat


def rate_matrix_frame(mat: RateMatrix, scenario: str) -> pl.DataFrame:
    return pl.DataFrame({"rate_scenario": [scenario] * len(mat), "tenor": [k[0] for k in mat],
                         "year": [k[1] for k in mat], "rate_pct": list(mat.values())}
                        ).with_columns(pl.col("year").cast(pl.Int64))


# =============================================================================
# 4.  Resolve the USER SETTINGS into concrete scenario paths
# =============================================================================


@dataclass
class Scenarios:
    growth: dict[str, dict[int, float]]                    # name -> {year: %}
    deficit: dict[str, dict[int, float]]                   # name -> {year: % of GDP}
    issuance: dict[str, dict[tuple[str, int], float]]      # name -> {(bucket, year): share}
    rates: dict[str, RateMatrix]                           # name -> rate matrix
    notes: list[str]                                       # what each setting resolved to


def _resolve_paths(setting, inp: ModelInputs, current: float | None, label: str, notes: list[str]):
    """None | number | '+x' | {year: v} | {name: ...}  ->  {name: {year: value}}."""

    def one(spec, name: str) -> dict[int, float]:
        if spec is None:
            if current is None:
                raise ValueError(f"{label}: None requested but the input file has no data to derive the current "
                                 f"value (history 'ngdp_growth_pct' or two GDP years; 'primary_deficit_pct_gdp' "
                                 f"or 'fiscal_deficit' + 'net_interest' for the base year)")
            notes.append(f"{label}[{name}] = current value {current:.2f} %, flat")
            return {y: current for y in inp.years}
        if isinstance(spec, (str, *Number)):
            lvl = _level(spec, current, f"{label}[{name}]")
            notes.append(f"{label}[{name}] = {lvl:.2f} %, flat")
            return {y: lvl for y in inp.years}
        if isinstance(spec, dict):
            pts = sorted((_year(k, inp.base_year), _level(v, current, f"{label}[{name}]")) for k, v in spec.items())
            knots = ([(inp.base_year, current)] if current is not None else []) + pts
            notes.append(f"{label}[{name}] = path through {[(y, round(v, 2)) for y, v in pts]}" +
                         (f", gliding from current {current:.2f} %" if current is not None and pts[0][0] > inp.years[0] else ""))
            return _interp_path(knots, inp.years)
        raise TypeError(f"{label}: unsupported setting {spec!r}")

    if isinstance(setting, dict) and setting and all(isinstance(k, str) for k in setting):
        return {name: one(spec, name) for name, spec in setting.items()}
    if setting == {}:
        setting = None
    name = "current" if setting is None else ("path" if isinstance(setting, dict) else "custom")
    return {name: one(setting, name)}


def _resolve_mix(setting, inp: ModelInputs, notes: list[str]):
    """None | {bucket: share} | {name: {bucket: share}}  ->  {name: full mix dict}."""
    names = [b.name for b in inp.buckets]

    def one(mixspec, name: str):
        mix = dict(inp.mix)                       # base-year column always = input file (it is history)
        if mixspec is None:
            notes.append(f"ISSUANCE_MIX[{name}] = current composition from input file")
            return mix
        unknown = set(mixspec) - set(names)
        if unknown:
            raise ValueError(f"ISSUANCE_MIX[{name}]: unknown bucket(s) {sorted(unknown)}; file buckets are {names}")
        tot = sum(float(v) for v in mixspec.values())
        if abs(tot - 1.0) > 1e-6:
            inp.warnings.append(f"ISSUANCE_MIX[{name}] sums to {tot:.4f}, not 1.0")
        for y in inp.years:
            for b in names:
                mix[(b, y)] = float(mixspec.get(b, 0.0))
        notes.append(f"ISSUANCE_MIX[{name}] = {mixspec}")
        return mix

    if setting is None or setting == {}:
        return {"current": one(None, "current")}
    named = all((v is None or isinstance(v, dict)) for v in setting.values()) and not (set(setting) & set(names))
    if named:
        return {n: one(s, n) for n, s in setting.items()}
    return {"custom": one(setting, "custom")}


def _resolve_rates(setting, inp: ModelInputs, notes: list[str], extra_tenors: list[str]):
    out = {"market": build_rate_matrix(inp, None, extra_tenors)}
    notes.append("RATE_SCENARIOS[market] = market-implied forwards (always included)")
    if setting is None or setting == {}:
        return out
    if isinstance(setting, Number):
        setting = {f"market{float(setting):+.2f}pp": setting}
    for name, spec in setting.items():
        if name == "market":
            raise ValueError("RATE_SCENARIOS: the name 'market' is reserved for the implied curve")
        out[name] = build_rate_matrix(inp, spec, extra_tenors)
        notes.append(f"RATE_SCENARIOS[{name}] = {spec}")
    return out


def resolve_scenarios(inp: ModelInputs, growth=None, deficit=None, mix=None, rates=None) -> Scenarios:
    notes: list[str] = []
    if inp.ngdp_growth_current is not None:
        notes.append(f"current nominal GDP growth = {inp.ngdp_growth_current:.2f} % ({inp.base_year-1}->{inp.base_year})")
    if inp.primary_deficit_current is not None:
        notes.append(f"current primary deficit = {inp.primary_deficit_current:.2f} % of GDP ({inp.base_year})")
    return Scenarios(
        growth=_resolve_paths(growth, inp, inp.ngdp_growth_current, "NGDP_GROWTH", notes),
        deficit=_resolve_paths(deficit, inp, inp.primary_deficit_current, "PRIMARY_DEFICIT_PCT_GDP", notes),
        issuance=_resolve_mix(mix, inp, notes),
        rates=_resolve_rates(rates, inp, notes, _curve_labels(inp)),
        notes=notes,
    )


def _curve_labels(inp: ModelInputs) -> list[str]:
    """Display labels for the spot-curve tenors, so the printed matrix shows the whole curve."""
    return ["O/N" if t == 0 else (f"{int(t)}Y" if float(t).is_integer() else f"{int(round(t*12))}M")
            for t in inp.curves.spot.t]


# =============================================================================
# 5.  The projection engine
# =============================================================================


def project(inp: ModelInputs, rates: RateMatrix, growth: dict[int, float], deficit: dict[int, float],
            mix: dict[tuple[str, int], float] | None = None) -> list[dict]:
    """Roll the debt forward; returns one dict per year, base year first.

    growth  : {year: nominal GDP growth %}
    deficit : {year: primary deficit % of GDP}
    rates   : output of build_rate_matrix()
    mix     : {(bucket, year): share}; None -> current composition from the input file
    """
    base, buckets = inp.base_year, inp.buckets
    mix = mix or inp.mix
    cohorts: dict[int, list[tuple[float, float]]] = {}      # maturity year -> [(amount, rate%)]

    # Base-year stock NOT covered by the ladder (typically bills): either an explicit amount,
    # or base-year gross issuance x the bucket's share.  Priced at the base-year rate.
    for b in buckets:
        if b.in_ladder:
            continue
        if b.base_outstanding is not None:
            amount = b.base_outstanding
        elif inp.issuance0 is not None:
            amount = inp.issuance0 * mix[(b.name, base)]
        else:
            raise ValueError(f"bucket '{b.name}' is not in the ladder: give 'base_outstanding' or history "
                             f"'gross_issuance' for {base}")
        cohorts.setdefault(base + b.maturity_years, []).append((amount, rates[(b.price_tenor, base)]))

    debt_prev, cost_prev, gdp_prev = inp.debt0, inp.cost0, inp.gdp0
    int_prev = cost_prev / 100.0 * debt_prev
    rows = [dict(year=base, nominal_gdp=gdp_prev, ngdp_growth_pct=None, primary_deficit_pct_gdp=None,
                 primary_deficit=None, maturing_ladder=None, maturing_cohorts=None, maturing_total=None,
                 cost_maturing_pct=None, gross_issuance=inp.issuance0, cost_new_issuance_pct=None,
                 net_new_debt=None, debt=debt_prev, avg_cost_pct=cost_prev, interest_expense=int_prev,
                 interest_expense_eoy_basis=int_prev, interest_pct_gdp=int_prev / gdp_prev * 100.0,
                 debt_pct_gdp=debt_prev / gdp_prev * 100.0, issued_to_maturing_ratio=None)]

    for y in inp.years:
        g, pd_pct = growth[y], deficit[y]
        gdp = gdp_prev * (1.0 + g / 100.0)
        pd_amt = pd_pct / 100.0 * gdp                        # primary deficit in money

        lad_amt, lad_cpn = inp.ladder[y]                     # existing bonds maturing this year
        coh = cohorts.pop(y, [])                             # model-issued cohorts maturing this year
        add_amt = sum(a for a, _ in coh)
        add_cost = (sum(a * r for a, r in coh) / add_amt) if add_amt > 0 else 0.0
        maturing = lad_amt + add_amt
        cost_exp = ((lad_amt * lad_cpn + add_amt * add_cost) / maturing) if maturing > 0 else 0.0

        # A primary surplus larger than the remaining stock retires it: debt is floored at zero and the rest of the surplus
        # (asset accumulation) is not modelled.  Buy-backs beyond the year's maturities leave at the stock's average cost.
        debt = max(debt_prev + pd_amt + int_prev, 0.0)
        net_new = debt - debt_prev
        issued = max(maturing + net_new, 0.0)                # gross issuance (interest lagged one year)
        extra_retired = max(-(maturing + net_new), 0.0)      # retired beyond maturities (only when the surplus exceeds them)

        share_sum = wsum = 0.0                               # split issuance into new cohorts
        for b in buckets:
            s, r = mix[(b.name, y)], rates[(b.price_tenor, y)]
            cohorts.setdefault(y + b.maturity_years, []).append((s * issued, r))
            share_sum += s
            wsum += s * r
        cost_new = wsum / share_sum                          # share-weighted new-issue rate

        cost = ((debt_prev * cost_prev - maturing * cost_exp - extra_retired * cost_prev + issued * cost_new) / debt) if debt > 0 else cost_prev
        interest = cost / 100.0 * (debt_prev + debt) / 2.0   # average-debt basis
        interest_eoy = cost / 100.0 * debt                   # end-of-year-debt basis (alternative convention)

        rows.append(dict(year=y, nominal_gdp=gdp, ngdp_growth_pct=g, primary_deficit_pct_gdp=pd_pct,
                         primary_deficit=pd_amt, maturing_ladder=lad_amt, maturing_cohorts=add_amt,
                         maturing_total=maturing, cost_maturing_pct=cost_exp, gross_issuance=issued,
                         cost_new_issuance_pct=cost_new, net_new_debt=net_new, debt=debt, avg_cost_pct=cost,
                         interest_expense=interest, interest_expense_eoy_basis=interest_eoy,
                         interest_pct_gdp=interest / gdp * 100.0, debt_pct_gdp=debt / gdp * 100.0,
                         issued_to_maturing_ratio=(issued / maturing) if maturing > 0 else None))
        debt_prev, cost_prev, gdp_prev, int_prev = debt, cost, gdp, interest
    return rows


# =============================================================================
# 6.  Run the whole grid
# =============================================================================

KEYS = ["country", "rate_scenario", "deficit_scenario", "issuance_scenario", "growth_scenario"]


@dataclass
class ModelOutput:
    interest_to_gdp: pl.DataFrame   # one row per scenario combination, one column per year (%)
    paths: pl.DataFrame             # full year-by-year detail (long)
    rate_matrices: pl.DataFrame     # tenor x year x rate scenario


def run_all(inp: ModelInputs, scen: Scenarios) -> ModelOutput:
    cc = inp.meta.get("country_code", inp.meta.get("country", "NA"))
    frames = []
    for rname, mat in scen.rates.items():
        for dname, dpath in scen.deficit.items():
            for iname, imix in scen.issuance.items():
                for gname, gpath in scen.growth.items():
                    frames.append(pl.DataFrame(project(inp, mat, gpath, dpath, imix)).with_columns(
                        pl.lit(cc).alias("country"), pl.lit(rname).alias("rate_scenario"),
                        pl.lit(dname).alias("deficit_scenario"), pl.lit(iname).alias("issuance_scenario"),
                        pl.lit(gname).alias("growth_scenario")))
    paths = pl.concat(frames, how="vertical_relaxed")
    paths = paths.select(KEYS + ["year"] + [c for c in paths.columns if c not in KEYS + ["year"]])

    # the headline table: scenario keys, then one column per year with interest / GDP in percent
    wide = (paths.select(KEYS + ["year", "interest_pct_gdp"])
            .pivot(on="year", index=KEYS, values="interest_pct_gdp"))
    rate_frames = [rate_matrix_frame(m, n) for n, m in scen.rates.items()]
    return ModelOutput(interest_to_gdp=wide, paths=paths, rate_matrices=pl.concat(rate_frames))


# =============================================================================
# 7.  Console report + CLI
# =============================================================================


def _cfg():
    return pl.Config(tbl_rows=500, tbl_cols=40, tbl_width_chars=250, float_precision=2,
                     tbl_hide_dataframe_shape=True, tbl_hide_column_data_types=True, fmt_str_lengths=40)


def print_report(inp: ModelInputs, scen: Scenarios, out: ModelOutput) -> None:
    cc, yH = inp.meta.get("country", "?"), inp.base_year + inp.horizon
    print(f"\n{'='*100}\n{cc}: interest expense / GDP, {inp.base_year}-{yH}  "
          f"(debt0={inp.debt0:,.0f}, avg cost0={inp.cost0:.2f}%, GDP0={inp.gdp0:,.0f})\n{'='*100}")
    for w in inp.warnings:
        print(f"WARNING: {w}")
    print("\n-- Assumptions in force --")
    for n in scen.notes:
        print("  " + n)
    with _cfg():
        print("\n-- New-issue rates by scenario (%, tenor x year) --")
        for rname in scen.rates:
            print(f"\n[{rname}]")
            print(out.rate_matrices.filter(pl.col("rate_scenario") == rname).pivot(on="year", index="tenor", values="rate_pct"))
        print("\n-- Interest expense / GDP (%) by scenario and year --")
        print(out.interest_to_gdp.drop("country"))
        print()


def _locate(csv: str) -> Path:
    """INPUT_CSV may be relative to the current folder or to this script's folder."""
    p = Path(csv)
    if p.exists():
        return p
    alt = Path(__file__).resolve().parent / csv
    if alt.exists():
        return alt
    raise FileNotFoundError(f"input CSV not found: {csv}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sovereign interest-expense scenario model (polars).")
    ap.add_argument("inputs", nargs="?", default=INPUT_CSV, help=f"input CSV (default: INPUT_CSV = {INPUT_CSV})")
    ap.add_argument("--out", default=OUTPUT_DIR, help="output folder (default: outputs/standalone/ at the repository root)")
    ap.add_argument("--quiet", action="store_true", help="do not print the console report")
    args = ap.parse_args(argv)

    csv = _locate(args.inputs)
    inp = load_inputs(csv, HORIZON_YEARS)
    scen = resolve_scenarios(inp, NGDP_GROWTH, PRIMARY_DEFICIT_PCT_GDP, ISSUANCE_MIX, RATE_SCENARIOS)
    out = run_all(inp, scen)

    out_dir = Path(args.out) if args.out else Path(__file__).resolve().parent.parent / "outputs" / "standalone"
    out_dir.mkdir(parents=True, exist_ok=True)
    cc = inp.meta.get("country_code", "XX")
    files = {f"{cc}_interest_to_gdp.csv": out.interest_to_gdp}
    if DETAIL_OUTPUT:
        files[f"{cc}_detail_paths.csv"] = out.paths
        files[f"{cc}_rate_matrices.csv"] = out.rate_matrices
    for name, df in files.items():
        df.write_csv(out_dir / name)

    if not args.quiet:
        print_report(inp, scen, out)
    print("Wrote:")
    for name in files:
        print(f"  {out_dir / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
