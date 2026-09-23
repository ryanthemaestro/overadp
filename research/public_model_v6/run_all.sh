#!/usr/bin/env bash
# Full rebuild of the v6 public projection model. Run from this directory.
set -euo pipefail
mkdir -p work out
[ -d data ] || ./fetch_data.sh                 # nflverse inputs (CC BY 4.0)
python3 pbp_extract.py                           # play-by-play opportunity features
python3 build_features.py                        # base feature table (v2)
cp work/features.pkl work/features_v2.pkl
[ -d cfbd_derived ] || { echo "Run cfbd_login.sh, cfbd_fetch.py, cfbd_derive.py first (college data)"; exit 1; }
python3 college.py                               # + college production (v5)
python3 routes.py                                # route participation (nflverse participation, CC BY-SA 4.0)
python3 add_routes.py                            # v6 feature table
python3 final.py                                 # walk-forward 2019-2025 + 2026 projections
python3 intervals.py                             # calibrated 80% ranges
python3 evaluate.py
[ -f adp/ffc_adp_2019_2025.csv ] && python3 adp_eval.py || echo "Skip ADP eval (run fetch_adp.py)"
