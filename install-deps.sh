#!/usr/bin/env bash
set -euo pipefail
sudo apt update
sudo apt install -y bluez bluetooth rfkill python3 python3-tk
sudo systemctl enable --now bluetooth
sudo rfkill unblock bluetooth || true
echo 'Dependencies installed. Run ./run.sh to launch BlueGuard.'
