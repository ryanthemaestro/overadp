#!/usr/bin/env bash
set -euo pipefail
if [[ ! -t 0 ]]; then printf 'Run this from an interactive terminal.\n' >&2; exit 1; fi
umask 077
python3 "$(dirname "$0")/cfbd_login.py"
