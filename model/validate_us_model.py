#!/usr/bin/env python3
"""
validate_us_model.py
====================
Proof that debt_model.py reproduces US_Debt_Model_v4.xlsx.  Independent of the USER SETTINGS
block: the workbook's own assumptions are hard-coded here.

It reads the workbook's CACHED values with openpyxl (no Excel needed) and compares them
with the Python engine:

  1. Rates_Matrix!C15:M23          vs  build_rate_matrix()  (market-implied rates)
  2. Model rows 55-58, 95-97, 107  vs  project() run with the workbook's own financing
     assumptions (GDP path 4.3/4.1/3.9/3.8.., primary deficit 2.8 % flat)
  3. Output rows 4-8               vs  the same run (avg cost, EOY-basis interest, int/GDP at 3/6/12 %)
  4. Output scenario helpers (rows 26-28 "cut to 2 %", rows 35-37 "curve reprices")
     vs the engine's cut_steep / curve_reprices scenarios.  These are NOT expected to
     match: the workbook helpers retire ALL maturing model-issued cohorts at the prior
     year's BILL rate (Output!E25:M25), i.e. 2y/3y/5y/7y notes issued at ~4.2-4.8 % are
     booked as if they cost ~2 % when they roll off, so too little cost leaves the stock
     and the workbook's average cost drifts up (4.83 % by 2036 vs 3.96 % here).  The
     engine tracks every cohort at its true issue rate.  For curve_reprices the whole
     curve is low so the shortcut barely matters (<0.03 pp).  Reported, not asserted.

Run:  python validate_us_model.py [US_Debt_Model_v4.xlsx] [US_debt_inputs.csv]
"""
import sys
from pathlib import Path

import openpyxl

import debt_model as dm

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # repository root (model/ sits one level down)
DATA = ROOT / "data"
XLSX = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA / "reference" / "US_Debt_Model_v4.xlsx"
CSV = Path(sys.argv[2]) if len(sys.argv) > 2 else DATA / "reference" / "US_debt_inputs_workbook.csv"

wb = openpyxl.load_workbook(XLSX, data_only=True)
model, output, rates_ws = wb["Model"], wb["Output"], wb["Rates_Matrix"]
COLS = "CDEFGHIJKLM"          # 2026 .. 2036 in every sheet used here
YEARS = list(range(2026, 2037))
TENORS = ["O/N", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

# the workbook's rate-cut scenarios, in absolute years
WB_SCENARIOS = {
    "cut_steep": {("O/N", 2027): 2.9, ("O/N", 2028): 2.1, ("O/N", 2029): 2.0,
                  ("1Y", 2027): 2.9, ("1Y", 2028): 2.1, ("1Y", 2029): 2.0},
    "curve_reprices": {("O/N", 2028): 2.0, ("1Y", 2028): 2.1, ("2Y", 2028): 2.4, ("3Y", 2028): 2.6,
                       ("5Y", 2028): 2.9, ("7Y", 2028): 3.2, ("10Y", 2028): 3.5, ("20Y", 2028): 3.9,
                       ("30Y", 2028): 4.0},
}


def row(ws, r, cols=COLS):
    return [ws[f"{c}{r}"].value for c in cols]


def compare(name, excel, python, tol, years=YEARS, assert_ok=True):
    worst, bad = 0.0, []
    for y, e, p in zip(years, excel, python):
        if e is None or p is None:
            continue
        d = abs(float(e) - float(p)) / max(1.0, abs(float(e)))   # relative for big $ numbers
        worst = max(worst, d)
        if d > tol:
            bad.append(f"{y}: excel={float(e):.6f} python={float(p):.6f} diff={d:+.2e}")
    status = "OK " if not bad else ("FAIL" if assert_ok else "diff")
    print(f"[{status}] {name:<58} max rel diff={worst:.2e}")
    for b in bad:
        print("        " + b)
    return not bad


inp = dm.load_inputs(CSV)
ok = True

print("\n1. Market-implied rate matrix vs Rates_Matrix!C15:M23")
market = dm.build_rate_matrix(inp, None, extra_tenors=TENORS)
for xl_row, tenor in zip(range(15, 24), TENORS):
    ok &= compare(f"Rates_Matrix row {xl_row} ({tenor})", row(rates_ws, xl_row),
                  [market[(tenor, y)] for y in YEARS], tol=1e-6)

print("\n2. Model sheet financing block (market rates, workbook GDP path, PD 2.8 % flat)")
xl_growth = {y: model[f"{c}103"].value for c, y in zip(COLS[1:], YEARS[1:])}   # row 103
xl_pd = {y: model[f"{c}105"].value for c, y in zip(COLS[1:], YEARS[1:])}       # row 105
base = dm.project(inp, market, xl_growth, xl_pd)
col = lambda k: [r[k] for r in base]

ok &= compare("Model row 104 nominal GDP", row(model, 104), col("nominal_gdp"), 1e-9)
ok &= compare("Model row 106 primary deficit $", row(model, 106), col("primary_deficit"), 1e-9)
ok &= compare("Model row 56+57 debt maturing (ladder + cohorts)",
              [a + b for a, b in zip(row(model, 56), row(model, 57))][1:], col("maturing_total")[1:], 1e-8, YEARS[1:])
ok &= compare("Model row 58 gross issuance", row(model, 58), col("gross_issuance"), 1e-8)
ok &= compare("Model row 55 debt held by public", row(model, 55), col("debt"), 1e-8)
ok &= compare("Model row 95 cost of maturing debt %", row(model, 95)[1:], col("cost_maturing_pct")[1:], 1e-7, YEARS[1:])
ok &= compare("Model row 96 cost of new issuance %", row(model, 96)[1:], col("cost_new_issuance_pct")[1:], 1e-7, YEARS[1:])
ok &= compare("Model row 97 AVERAGE COST OF DEBT %", row(model, 97), col("avg_cost_pct"), 1e-7)
ok &= compare("Model row 107 interest expense (avg-debt basis)", row(model, 107), col("interest_expense"), 1e-7)
ok &= compare("Model row 108 issued/expired ratio", row(model, 108)[1:], col("issued_to_maturing_ratio")[1:], 1e-7, YEARS[1:])

print("\n3. Output sheet rows 4-8 (same run)")
ok &= compare("Output row 4 average cost (fraction)", row(output, 4), [c / 100 for c in col("avg_cost_pct")], 1e-7)
ok &= compare("Output row 5 interest expense (cost x EOY debt)", row(output, 5), col("interest_expense_eoy_basis"), 1e-7)
for xl_row, g in [(6, 0.03), (7, 0.06), (8, 0.12)]:
    py = [i / (inp.gdp0 * (1 + g) ** t) for t, i in enumerate(col("interest_expense_eoy_basis"))]
    # Output!C6 is the historical 3.24 % (Model!M41), not the model's 3.47 %: skip year 0
    ok &= compare(f"Output row {xl_row} interest/GDP at {g:.0%} growth (2027-36)", row(output, xl_row)[1:], py[1:], 1e-7, YEARS[1:])

print("\n4. Workbook scenario helpers vs engine scenarios  (differences EXPECTED, see docstring)")
for scen, rows_ in [("cut_steep", (26, 27, 28)), ("curve_reprices", (35, 36, 37))]:
    run = dm.project(inp, dm.build_rate_matrix(inp, WB_SCENARIOS[scen]), xl_growth, xl_pd)
    r_debt, r_cost, r_int = rows_
    compare(f"{scen}: debt path    (Output row {r_debt})", row(output, r_debt), [r["debt"] for r in run], 1e-6, assert_ok=False)
    compare(f"{scen}: avg cost %   (Output row {r_cost})", row(output, r_cost), [r["avg_cost_pct"] for r in run], 1e-6, assert_ok=False)
    compare(f"{scen}: interest $   (Output row {r_int})", row(output, r_int), [r["interest_expense"] for r in run], 1e-6, assert_ok=False)

print("\nRESULT:", "ALL EXACT CHECKS PASSED" if ok else "SOME EXACT CHECKS FAILED")
sys.exit(0 if ok else 1)
