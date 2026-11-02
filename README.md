# How Will Government Interest Expense Develop Over the Next Decade?

A bond-by-bond projection of sovereign interest expense as a share of GDP for nine countries (United States, China, United Kingdom, France, Germany, Italy, Canada, Australia, Denmark) from 2026 to 2036, under four joint scenarios, with the sub-sovereign tier (provinces, states, local governments, Länder, agencies) layered on top.

The question the project asks: **given today's debt stocks, coupons, maturity profiles and market-implied yield curves, how much of GDP will governments be paying in interest by 2036, which assumptions decide the answer, and who ends up paying?**

The key deliverable is **[`outputs/Scenario_Summary.pdf`](outputs/Scenario_Summary.pdf)** (nine pages: where the burden stands today, where it can go by 2036, what it is most sensitive to, the assumptions behind each case, and sources). The longer decks and reports are listed in section 5.

---

## Contents

1. [Approach & Key Findings](#1-approach--key-findings)
   1.1 [The model in brief](#11-the-model-in-brief)
   1.2 [Country readings](#12-country-readings)
   1.3 [Two things to keep in mind when quoting the numbers](#13-two-things-to-keep-in-mind-when-quoting-the-numbers)
   1.4 [Where the burden stands today (2022 → 2026)](#14-where-the-burden-stands-today-2022--2026)
   1.5 [Where it can go by 2036](#15-where-it-can-go-by-2036)
   1.6 [What the ratio is most sensitive to](#16-what-the-ratio-is-most-sensitive-to)
   1.7 [The bull case: level and direction of travel](#17-the-bull-case-level-and-direction-of-travel)
2. [The Four Scenarios](#2-the-four-scenarios)
3. [Data](#3-data)
4. [Code & Workflow](#4-code--workflow)
5. [Outputs](#5-outputs)
6. [How to Run](#6-how-to-run)
7. [Glossary of Concepts](#7-glossary-of-concepts)
8. [References & Sources](#8-references--sources)
9. [Caveats](#9-caveats)

---

## 1. Approach & Key Findings

### 1.1 The model in brief

A **cohort roll-forward** of each country's marketable central-government debt, built in Python and validated line by line against the original US Excel model. Each year the government refinances maturing bonds, borrows the primary deficit and last year's interest, and prices new issuance at the **market-implied forward rate** for the tenors it actually issues; the average cost of the stock updates as old coupons roll off, and interest over nominal GDP is the output.

Nine countries run on October 2026 Bloomberg security-level inputs (2016 inputs for a back-test). A **tier-1 overlay** adds sub-sovereign debt: Canadian provinces, Australian states, Chinese local-government bonds and LGFVs (bonds and loans), German Länder, French social-security agencies, Italian quasi-sovereigns. Four **joint scenarios** move growth, the primary balance, the curve and tier 1 together (section 2): **base** (market pricing), **bull** (AI boom, then disinflation), **bear** (inflation persists, higher for longer) and **financial repression** (inflation of 3–4% with the curve capped).

### 1.2 Country readings

**United States.** A two-part bet: that an AI capex boom delivers, and that the proceeds are banked. The boom alone leaves the 2036 bill above 3% of GDP; only the surplus gets it to 2.2%. If the boom disappoints, the base case is 6% and the exits are a surplus or repression. The US has the fastest-repricing stock in the sample and the only front-end-driven bill, so fiscal pressure lands on the policy rate.

**China.** Already running a partial financial repression: rates are capped by forcing captive savers to hold government and local paper, while a general-government deficit of 7–8% of GDP keeps nominal growth up. The cap has worked on price (average rate 3.9% → 3.3% since 2022) but not on quantity, so the bill has stayed flat at 3.7% rather than falling and savers are subsidising local government indefinitely. The bear case is the cap failing; administered regimes rarely fail smoothly. Because LGFV bonds and loans are included, these figures run far above the official measure.

**Europe.** France and Italy have the greatest need for repression and the greatest obstacle to it: in the euro area it is an ECB decision that makes German savers pay for France and Italy, and Germany does not need it. France has Italy's dynamics without Italy's surplus; its best domestic outcome ends where the ECB repression it cannot choose would. Italy's surplus stops the stock growing but not repricing. The UK is outside this: repression there is a national option, and the slowest-repricing stock in the sample buys it time.

**Canada and Australia.** The sovereigns are sound; the risk is provinces and states that borrow long and offshore, make up 40–50% of the consolidated bill, and have only a discretionary backstop. On interest-to-revenue, the US is the stretched one, not them.

**Denmark.** The bull case retires the whole stock by 2035. Nothing in the model troubles Denmark.

**The common thread.** Every exit runs through the bondholder: waiting for AI in the US, captive savers in China, German savers in a euro repression, foreign buyers staying put in Canada and Australia.

### 1.3 Two things to keep in mind when quoting the numbers

- **These are coupon costs on marketable central-government debt, not general-government interest.** IMF figures run higher because they add the inflation uplift on linkers, every level of government and accrual items; the model's US 1.9% for 2022 matches CBO's net interest, the IMF's general-government figure is 3.1%. China is the exception in the other direction, because the model includes LGFVs.
- **Two per cent is not a historical norm.** It was the ZIRP-era norm; G7 interest bills ran at 4–5% of GDP in the 1980s and 1990s, and the base cases here return to that world.

### 1.4 Where the burden stands today (2022 → 2026)

![Interest / GDP in 2022 and 2026](outputs/figures/then_vs_now.png)

| | 2022 | 2026 | Average rate 2022 | Average rate 2026 |
|---|---|---|---|---|
| Italy | 2.5 | 3.7 | 2.1 | 3.2 |
| China | 3.6 | 3.7 | 3.9 | 3.3 |
| United States | 1.9 | 3.3 | 2.3 | 3.6 |
| United Kingdom | 1.8 | 2.7 | 2.0 | 3.1 |
| France | 1.4 | 2.3 | 1.5 | 2.3 |
| Canada | 1.9 | 2.3 | 2.7 | 3.0 |
| Australia | 1.2 | 1.9 | 2.1 | 3.4 |
| Germany | 0.7 | 1.1 | 1.2 | 1.9 |
| Denmark | 0.3 | 0.3 | 1.5 | 1.8 |

The rise since 2022 is almost entirely price, not quantity: debt ratios barely moved while average rates rose about a point as 2015–21 paper rolled into today's curve. Italy's jump is repricing (half its stock rolled from 0–1% coupons to 3.5–4.5%; its surplus only started in 2024). China is the only country whose average rate fell.

### 1.5 Where it can go by 2036

![How interest expense over GDP can develop by 2036](outputs/figures/range_2036.png)

**Interest / GDP in 2036, total including tier 1 (% of GDP)**

| | 2026 | Bull | Base | Bear | Repression |
|---|---|---|---|---|---|
| United States | 3.3 | 2.2 | 5.9 | 7.4 | 2.9 |
| France | 2.3 | 2.8 | 6.6 | 8.6 | 2.8 † |
| Italy | 3.8 | 2.7 | 5.3 | 6.8 | 2.6 † |
| United Kingdom | 2.7 | 2.1 | 4.1 | 5.3 | 2.3 |
| China | 3.7 | 2.4 | 4.3 | 7.1 | 3.3 |
| Australia | 1.9 | 2.4 | 4.2 | 5.8 | 2.7 |
| Canada | 2.3 | 1.8 | 2.7 | 4.0 | 1.6 |
| Germany | 1.1 | 0.9 | 2.3 | 3.3 | 1.2 † |
| Denmark | 0.3 | 0.0 | 0.3 | 0.6 | 0.2 |

† ECB-bloc case: for euro members repression is a decision taken in Frankfurt, not a national option.

† ECB-bloc case: for euro members repression is decided in Frankfurt, not nationally.

On market pricing the US goes from 3.3% to 5.9% and France from 2.3% to 6.6%, mechanically: 2010s coupons reprice to today's curve while 3–5% primary deficits add debt. The bear is 7.4% and 8.6%. Repression is the one case that holds the ratio flat, and it is Italy's best cell and France's equal-best; it is paid for by a decade of negative real returns to bondholders. The UK, Canada, Australia, Germany and Denmark are manageable in every case.

### 1.6 What the ratio is most sensitive to

![Sensitivity pies](outputs/figures/pies.png)

*One-unit moves from the base case (+1 pp/yr growth, +1 pt of GDP deficit, +100 bp on one curve segment, +1 pp/yr tier-1 growth, +1 year tier-1 WAM, +100 bp tier-1 spread), averaged over up and down.*

**Points of GDP of 2036 interest / GDP per unit move**

| | Growth +1 pp | Deficit +1 pt | Front end (1–3Y) +100 bp | Belly (5–7Y) | Long end (10–30Y) | Tier-1 growth | Tier-1 spread |
|---|---|---|---|---|---|---|---|
| United States | −0.45 | +0.42 | +0.67 | +0.39 | +0.39 | | |
| France | −0.58 | +0.53 | +0.32 | +0.28 | +0.85 | +0.05 | +0.08 |
| Italy | −0.53 | +0.45 | +0.27 | +0.48 | +0.49 | +0.01 | +0.02 |
| United Kingdom | −0.36 | +0.49 | +0.15 | +0.21 | +0.44 | | |
| China | −0.37 | +0.20 | +0.12 | +0.30 | +0.85 | +0.26 | +0.68 |
| Australia | −0.38 | +0.48 | +0.04 | +0.09 | +0.66 | +0.19 | +0.32 |
| Canada | −0.26 | +0.32 | +0.13 | +0.09 | +0.41 | +0.13 | +0.17 |
| Germany | −0.19 | +0.31 | +0.12 | +0.15 | +0.41 | +0.04 | +0.06 |
| Denmark | −0.03 | +0.26 | +0.01 | +0.00 | +0.06 | | |

The curve is the largest lever per unit everywhere but Denmark, and the US and France are three times as rate-sensitive as the slow-rolling UK. The US is the only front-end story; everyone else is a long-end story. Tier-1 WAM is immaterial; tier-1 growth and spread matter in China, Australia and Canada. A sensitivity is not a decomposition of a scenario: the deficit is the US's weakest lever per unit yet does as much work as the curve in the bull, because the bull moves it six points.

### 1.7 The bull case: level and direction of travel

![Bull-case paths](outputs/figures/bull_paths.png)

| | 2026 | 2030 (end of phase 1) | 2036 | Slope 2034→36, pp/yr | Average cost 2030 → 2036 |
|---|---|---|---|---|---|
| Italy | 3.75 | 4.14 | 2.71 | −0.22 | 3.85 → 2.94 |
| United States | 3.30 | 3.76 | 2.22 | −0.15 | 4.33 → 3.04 |
| United Kingdom | 2.65 | 2.94 | 2.14 | −0.12 | 3.81 → 3.26 |
| France | 2.34 | 3.65 | 2.79 | −0.10 | 3.66 → 3.09 |
| China | 3.70 | 2.98 | 2.40 | −0.08 | 1.93 → 2.02 |
| Canada | 2.29 | 2.36 | 1.79 | −0.08 | 3.32 → 2.75 |
| Germany | 1.11 | 1.39 | 0.91 | −0.06 | 2.68 → 2.22 |
| Australia | 1.94 | 2.50 | 2.40 | −0.03 | 3.98 → 3.76 |

The boom alone is not enough; the surplus by 2030 does the work. Phase 1 is expensive: the US and France add 1–1.7 pt of GDP of interest by 2030 financing a boom at today's curve. Fast repricing (US cost 4.3% → 3.0%) and a surplus (Italy) make the steepest fallers; Australia is flat because its states keep borrowing through the cuts.

---

## 2. The Four Scenarios

Every number is defined relative to each country's own starting point. Full per-country tables are the last pages of `outputs/Scenario_Summary.pdf`.

| | Nominal growth | Primary balance | Yield curve | Tier 1 |
|---|---|---|---|---|
| **Base** (market) | Average of the 2016–25 CAGR and the latest year | Held at today's level | Market-implied forwards from today's curve | Middle historical growth pace, current WAM, through-cycle spread |
| **Bull** (AI boom, then disinflation) | 2027–30: base +1.0. From 2031: back to base for the US, UK, Canada, Australia; base +1.0 for euro members, Denmark, China | Glides from today to a surplus of at least 1% of GDP by 2030 (1.5 pt better where already in surplus), then held | 2027–30 on market forwards; glides over 2031–32 to a low terminal curve (US 2.0 / 2.2 / 3.0 / 3.5 at 1, 2, 10, 30 years; France's spread over Bunds tightened to ~100 bp) and held | Middle pace; the longer WAM and tight spread phased in over 2031–32 |
| **Bear** (inflation persists, higher for longer) | Base −0.5 | 1.5 pt of GDP worse by 2036 | No cuts: front end +25 bp over market; term premium rebuilds with the fiscal position (30-year +110 bp high-debt, +65 bp low-debt; France +50, Italy +75 bp of spread from 10 years out); reached by 2028 and held as a spread over market forwards | Fastest historical pace, shorter WAM, stressed spread |
| **Repression** (inflation 3–4%, curve capped) | Base +1.0 (inflation, not real growth) | Held (repression substitutes for consolidation) | Full easing cycle held for the decade; long end capped with the term premium near zero (10-year ≈ 1-year + 1.3); reached by 2028 and held as a level. An ECB-bloc case for Germany, France, Italy; shallower cap for Australia | Middle pace, longer WAM, tight spread (captive banks absorb it) |

**China** is handled on its own terms: growth 6 / 5 / 4 / 5% (bull / base / bear / repression); bull and repression are the yield cap holding (market forwards), base is a developed-market steepening of its administered curve (long end +0.75 to +1 pt), bear is the cap failing (parallel +1.5 pt). Its tier 1 includes LGFV bank and trust loans (~RMB 42tn), which no securities screen captures; LGFV bonds and loans retire as the swap replaces them with local-government bonds, so swapped debt is not counted twice.

Repression is a **joint** scenario and is never crossed with the other levers. The 27-cell lever grid (growth low/base/high × deficit improves/holds/worsens × curve bull/market/bear) is kept for the sovereign-only report and the sensitivity analysis.

---

## 3. Data

| Input | Source | Where in the repo |
|---|---|---|
| Bond-level stock, coupons, maturities (every live central-government bond and bill, 2026 and 2016 snapshots) | Bloomberg SRCH pulls, dated 16 Oct 2026; 2016 pulls dated 30 Sep 2016 (US), 31 Mar 2016 (UK, Canada), 30 Jun 2016 (Australia), end-2016 (others). Issue dates estimated from market conventions and identifier order. | Processed into `data/inputs/<vintage>/<CC>_debt_inputs.csv` (one long-format file per country with per-line notes). The raw pulls are licensed and are **not** in the repository. |
| On-the-run yield curves, short-end points, China / Denmark / Australia curves | Bloomberg yields file (16 Oct 2026); policy rates and 1-year bills from central banks and debt offices (mid-Oct 2026); ChinaBond CGB curve (20 Oct 2026); Danish and Australian quotes (15–19 Oct 2026) | `data/inputs/2026/*.csv`, `spot_curve` section |
| 2016 spot curves | Author's table (overnight, 2y, 5y, 10y, long bond) | `data/inputs/2016/*.csv` |
| Term premia (5y, 10y; 2016 and 2026) | OIS decomposition workbook (US, Canada, UK); euro members and Denmark = EUR OIS term premium + Bund swap spread + 10-year sovereign spread versus Bunds (Eurostat convergence yields Dec 2016; market quotes Oct 2026); Australia set equal to Canada; China a judgment estimate | `data/inputs/*/*.csv`, `implied_tp` and `static_tp` sections |
| General-government fiscal balances | IMF World Economic Outlook, October 2026 (UK 2026 from the April 2026 Fiscal Monitor; US and UK 2016 via FRED) | `data/inputs/*/*.csv`, `history` section |
| Nominal GDP, local currency | World Bank WDI, GDP current LCU (NY.GDP.MKTP.CN) | `data/inputs/*/*.csv`, `history` section |
| Sub-sovereign stocks, balances, WAM, spreads (2016–2026) | Canadian provincial financing authorities (ON, QC, AB, BC); Australian state treasury corporations (NSW TCorp, TCV, QTC, WATC); Chinese MoF local-government bond data and LGFV bond buckets by rating; German Länder debt statistics; CADES, Unédic, ACOSS (plus SFIL/CAFFIL, Bpifrance, AFL, IDFM as exposure variants); Italian CDP, FS, regional sinkers, CDP postal savings | `data/tier1/*.csv`, method in `data/tier1/tier1_model_notes.pdf` |
| 2022 sovereign stocks and average coupons (for the then-versus-now chart) | US Treasury (MSPD and average interest rates, Dec 2022); Finance Canada Debt Management Report 2022-23; UK DMO portfolio statistics with ONS/OBR debt interest net of RPI uplift; AFT and Cour des comptes; Italian MEF Rapporto sul debito pubblico 2022; Finanzagentur Kreditaufnahmebericht 2022; Danmarks Nationalbank Central government borrowing and debt 2022; AOFM Annual Report 2021-22; Chinese MoF 2022 central final accounts | Hardcoded with sources in `model/then_vs_now.py`; written to `outputs/2026/INTEREST_THEN_VS_NOW.csv` |
| US reference model | `US_Debt_Model_v4.xlsx` and its input file, used only to validate the engine | `data/reference/` |

---

## 4. Code & Workflow

```
Sovereign-Interest-Expense-Scenarios/
├── README.md
├── requirements.txt
├── model/
│   ├── debt_model.py          the engine: curve machinery, input loader, cohort roll-forward, scenario grid
│   ├── build_inputs.py        Bloomberg pulls -> data/inputs/*.csv (needs the raw pulls; provenance only)
│   ├── run_scenarios.py       scenario definitions (joint cases, curve tables, China rules) and the country x vintage runs
│   ├── tier1_overlay.py       sub-sovereign blocks: growth / WAM / spread settings, consolidated paths
│   ├── scenario_lines.py      the two decks (Scenario_Summary.pdf, Scenario_Lines.pdf) and their CSVs
│   ├── then_vs_now.py         the 2022-against-2026 chart (imported by scenario_lines.py)
│   ├── make_report.py         Debt_Service_Report.pdf: sovereign-only lever grid, country pages, r vs g, 2016 back-test
│   ├── make_tier1_report.py   Tier1_Overlay_Report.pdf
│   ├── validate_us_model.py   engine-versus-workbook proof
│   └── run_all.py             runs the chain in order
├── data/
│   ├── inputs/2026/           nine model input files (long format: section,item,sub_item,period,value,notes)
│   ├── inputs/2016/           the 2016 vintage for the back-test
│   ├── tier1/                 six sub-sovereign files + method notes
│   └── reference/             the US workbook and its input file (validation only)
└── outputs/
    ├── Scenario_Summary.pdf   <- start here
    ├── Scenario_Lines.pdf, Debt_Service_Report.pdf, Tier1_Overlay_Report.pdf, Interest_Then_vs_Now.pdf
    ├── figures/               every chart as PNG
    ├── 2026/                  results: ALL_interest_to_gdp, ALL_detail_paths, ALL_assumptions, SCENARIO_*, TIER1_assumptions,
    │                          CONSOLIDATED_paths, INTEREST_THEN_VS_NOW
    └── 2016/                  back-test results
```

**Workflow.** `run_scenarios.py` resolves each country's assumptions relative to its own inputs and runs the 27-cell lever grid plus the joint repression cell for both vintages. `tier1_overlay.py` rolls each sub-sovereign block forward under the joint cases and re-runs the sovereign on a central-only balance. `scenario_lines.py` builds the joint bull / base / bear / repression paths (sovereign plus tier 1), the sensitivity analysis and both decks, importing the 2022 comparison from `then_vs_now.py`. The two report scripts produce the longer PDFs. Every chart is regenerated on each run, so the decks always reflect the current settings.

**Settings live at the top of the scripts, not in the data.** Scenario curves, growth and deficit rules are constants in `run_scenarios.py` (`CURVES_2028`, `BULL_TERMINAL`, `GROWTH_DELTA`, `BULL_SURPLUS`, China rules); tier-1 settings in `tier1_overlay.py` (`T1_CASE`, `WAM_MULT`, `COST0`, `BLOCKS`); the engine's own defaults in the USER SETTINGS block of `debt_model.py`. Input files contain data only.

---

## 5. Outputs

| File | What it is |
|---|---|
| **`outputs/Scenario_Summary.pdf`** | The nine-page summary: 2022 → 2026, the 2036 range chart, sensitivity pies, one assumptions page per case, sources. |
| `outputs/Scenario_Lines.pdf` | The full deck: stacked bars per case (2026 vs 2036, tier 1 stacked), growth assumptions, growth-minus-interest charts, sensitivity table by tenor, CAGR table, bull-case direction of travel, assumptions, sources. |
| `outputs/Debt_Service_Report.pdf` | Sovereign-only report on the lever grid: headline table, methodology, cross-country structure charts, a page per country, the r-versus-g Italy case study, the 2016 → 2026 back-test, caveats. |
| `outputs/Tier1_Overlay_Report.pdf` | The sub-sovereign overlay: how much tier 1 adds, the explicit assumptions per block, what drives the add, country notes, exposure variants. |
| `outputs/Interest_Then_vs_Now.pdf` | Standalone copy of the 2022-against-2026 page. |
| `outputs/2026/SCENARIO_LINES.csv` | Year-by-year path of every joint case per country: sovereign and tier-1 interest / GDP, debt / GDP, average costs. |
| `outputs/2026/SCENARIO_ASSUMPTIONS.csv` | The resolved assumptions behind each case per country (growth, balance, curve points in 2028 and 2036, tier-1 settings). |
| `outputs/2026/SCENARIO_SENSITIVITY.csv` | Unit sensitivities by lever and tenor. |
| `outputs/2026/ALL_interest_to_gdp.csv`, `ALL_detail_paths.csv`, `ALL_assumptions.csv` | The sovereign-only lever grid: one row per scenario cell, the full yearly detail, and every resolved path. |
| `outputs/2026/TIER1_assumptions.csv`, `CONSOLIDATED_paths.csv` | Tier-1 block settings per case and the consolidated sovereign-plus-tier-1 paths. |
| `outputs/2026/INTEREST_THEN_VS_NOW.csv` | The 2022 and 2026 figures with their sources. |
| `outputs/2016/` | The back-test vintage. |

---

## 6. How to Run

```bash
git clone <this repository>
cd Sovereign-Interest-Expense-Scenarios
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python model/run_all.py              # rebuilds every CSV, chart and PDF under outputs/
python model/run_all.py --validate   # also re-runs the engine-versus-workbook validation first
```

Individual steps can be run on their own from `model/` (`python run_scenarios.py`, `python scenario_lines.py`, ...). To change a scenario, edit the constants at the top of `model/run_scenarios.py` or `model/tier1_overlay.py` and rerun. To add a country, add a `data/inputs/2026/<CC>_debt_inputs.csv` in the same long format (the engine reads any file with the documented sections) and append the code to the country lists at the top of the scripts. `build_inputs.py` is included for provenance; it needs the Bloomberg pulls in `data/bloomberg/`, which are not redistributed.

Requires Python 3.11+ and the packages in `requirements.txt` (polars, matplotlib, reportlab, openpyxl, pypdf).

---

## 7. Glossary of Concepts

- **Interest / GDP.** Average cost × average debt over nominal GDP, on marketable central-government debt plus tier 1; not national-accounts general-government interest (1.3).
- **Primary balance.** The budget balance before interest; here the IMF general-government balance less modelled interest, central-only where tier 1 exists (+ = deficit in the files).
- **Average cost of the stock.** Coupon-weighted interest rate on outstanding debt, bills at the 1-year rate; it moves only as debt rolls.
- **Market-implied forward rate.** The rate at which a tenor can be issued in a future year, implied by today's curve: f(h, m) = [y(h+m)(h+m) − y(h)h] / m, term premium stripped and today's premium added back.
- **Term premium.** Compensation in a long yield beyond expected short rates; European premia include the sovereign spread over Bunds.
- **Cohort roll-forward.** Each year's issuance is tracked with its own rate and maturity and refinanced at that year's forward when it matures.
- **Maturity ladder / issuance composition.** Bonds maturing each year with their coupons; the share of new issuance by tenor (held constant).
- **WAM.** Weighted average remaining maturity; a short WAM means rates reach the average cost quickly.
- **Tier 1.** Sub-sovereign and quasi-sovereign debt the public sector services but national screens omit, modelled as blocks with a growth rate, WAM and spread.
- **LGFV.** Chinese local-government financing vehicle, funded by bonds and bank/trust loans, partly refinanced into local-government bonds through the debt swap.
- **Joint scenario vs lever grid.** One story moving every assumption together, versus one assumption at a time with the rest at base (used for the sensitivity).
- **Key-rate (segment) sensitivity.** The effect of +100 bp on one part of the curve only; front, belly and long add up to a parallel shift.
- **Financial repression.** Nominal rates held below inflation with captive buyers, so debt erodes at bondholders' expense.
- **ECB-bloc case.** A scenario a euro member cannot choose alone because it needs the ECB to act for the whole area.
- **r versus g.** Average interest rate against nominal growth; with r > g a primary surplus is needed just to hold debt/GDP flat.
- **Index-linked uplift.** Inflation compensation accrued on linkers, booked as interest in national accounts but not a coupon.

---

## 8. References & Sources

**Market and bond data**
- Bloomberg L.P., SRCH security screens of central-government bonds and bills (16 Oct 2026 and 2016 snapshots) and on-the-run yield curves (16 Oct 2026). Licensed; not redistributed.
- ChinaBond, CGB yield curve, 20 Oct 2026.
- Central banks and debt offices for policy rates and 1-year bill yields, mid-October 2026 (Federal Reserve, Bank of Canada, Bank of England, ECB, Danmarks Nationalbank, Reserve Bank of Australia, People's Bank of China).
- Eurostat, EMU convergence criteria series (10-year yields, December 2016) for the 2016 sovereign spreads.

**Macro and fiscal**
- International Monetary Fund, *World Economic Outlook* database, October 2026, and *Fiscal Monitor*, April 2026 (general-government net lending/borrowing, primary balance, gross debt). IMF DataMapper series `ie` (interest paid on public debt, % of GDP) used for the general-government comparison in section 1.3.
- World Bank, *World Development Indicators*, GDP (current LCU), NY.GDP.MKTP.CN.
- Federal Reserve Bank of St. Louis, FRED (IMF WEO series for US and UK 2016 balances).

**2022 sovereign stocks and average rates**
- US Department of the Treasury, Fiscal Data: *Monthly Statement of the Public Debt* and *Average Interest Rates on U.S. Treasury Securities*, December 2022.
- Department of Finance Canada, *Debt Management Report 2022–2023*.
- UK Debt Management Office, *Quarterly Review January–March 2023* and *Annual Review 2022–23*; Office for National Statistics, *Public sector finances* (central-government debt interest); Office for Budget Responsibility on the RPI uplift on index-linked gilts.
- Agence France Trésor, *Rapport d'activité 2022* and monthly bulletins; Cour des comptes, *Le budget de l'État en 2022* and *Note d'exécution budgétaire 2022, Engagements financiers de l'État*; Sénat, rapport sur le projet de loi de règlement 2022.
- Ministero dell'Economia e delle Finanze, *Rapporto sul debito pubblico 2022* and *Public Debt Report 2023*.
- Bundesrepublik Deutschland Finanzagentur, *Kreditaufnahmebericht des Bundes 2022*; Institut der deutschen Wirtschaft on the average rate of federal debt.
- Danmarks Nationalbank, *Central government borrowing and debt 2022*.
- Australian Office of Financial Management, *Annual Report 2021–22*.
- Ministry of Finance of the People's Republic of China, 2022 central government final accounts (国债余额, 债务付息支出).

**Sub-sovereign**
- Ontario Financing Authority, Ministère des Finances du Québec, Alberta Treasury Board and Finance, BC Ministry of Finance (debt, balances, effective interest rates); Financial Accountability Office of Ontario, interprovincial comparisons.
- NSW Treasury Corporation, Treasury Corporation of Victoria, Queensland Treasury Corporation, Western Australian Treasury Corporation, annual reports.
- Chinese Ministry of Finance, *China Local Government Bond Market Reports*; LGFV bond data by rating bucket.
- Deutsche Bundesbank, *Länderfinanzen* and Länder debt statistics.
- CADES, Unédic and ACOSS annual and financial reports; Cassa Depositi e Prestiti and Ferrovie dello Stato disclosures.

**Model**
- `US_Debt_Model_v4.xlsx`, the original US workbook the engine reproduces (`data/reference/`).

---

## 9. Caveats

- **Definition.** Coupon costs on marketable central debt plus the defined tier-1 blocks: lower than all-in public-sector interest (no linker uplift, no sub-national debt outside tier 1), higher than official Chinese figures (LGFVs included).
- **No feedback.** Growth, the balance and the curve are separate levers; the joint scenarios impose the correlations by assumption.
- **No buyers' strike.** Paths are priced, not the event that ends them.
- **Estimated issue dates and composition.** The Bloomberg pulls carry no issue dates; they are inferred and the issuance mix is held constant.
- **Scenario levels are judgments.** The 2016 → 2026 back-test shows market forwards under-predicted every bill but Denmark's and China's, so the base case is a central estimate conditional on the curve, not a forecast of it.
- **Tier-1 and 2022 effective rates** carry roughly ±0.3 pt of uncertainty; estimates are marked in the sources.

---

*Mikkel Borggren, Yale School of Management, 2026. Model built in Python with polars, matplotlib and reportlab.*
