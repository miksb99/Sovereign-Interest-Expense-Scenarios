#!/usr/bin/env python3
"""
run_all.py -- rebuild every output from the input files, in dependency order.

    python model/run_all.py            # scenarios -> tier-1 overlay -> scenario decks -> reports -> then-vs-now chart
    python model/run_all.py --validate # also re-run the engine-versus-workbook validation first

Steps (each is a standalone script that can be run on its own):
  1. run_scenarios.py      lever grid + joint cases for every country and vintage      -> outputs/<vintage>/ALL_*.csv
  2. tier1_overlay.py      sub-sovereign blocks and the consolidated paths             -> outputs/2026/TIER1_*.csv, CONSOLIDATED_paths.csv
  3. scenario_lines.py     the joint-case decks (Scenario_Summary.pdf, Scenario_Lines.pdf) and their CSVs; imports then_vs_now
  4. make_tier1_report.py  Tier1_Overlay_Report.pdf
  5. make_report.py        Debt_Service_Report.pdf (sovereign-only lever grid, country pages, 2016 back-test)
  6. then_vs_now.py        Interest_Then_vs_Now.pdf (standalone copy of the 2022-against-2026 page)
build_inputs.py is not part of the chain: it regenerates data/inputs/ from the Bloomberg pulls, which are not in the repository.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ["run_scenarios.py", "tier1_overlay.py", "scenario_lines.py", "make_tier1_report.py", "make_report.py", "then_vs_now.py"]

if __name__ == "__main__":
    steps = (["validate_us_model.py"] if "--validate" in sys.argv else []) + STEPS
    for i, script in enumerate(steps, 1):
        print(f"\n[{i}/{len(steps)}] {script}", flush=True)
        subprocess.run([sys.executable, str(HERE / script)], check=True, cwd=HERE)
    print("\nall outputs rebuilt under", HERE.parent / "outputs")
