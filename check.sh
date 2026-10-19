#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m py_compile blueguard.py
echo 'Python syntax check passed.'
