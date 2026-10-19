# BlueGuard Bluetooth Scanner

A Python/Tkinter Bluetooth discovery and authorized connection tool for Kali Linux and Debian-based systems. Uses BlueZ `bluetoothctl` for Bluetooth Classic and BLE discovery, provides MAC-address selection, explicit-confirmation Pair/Connect/Disconnect actions, and exports scan inventory to CSV/JSON.

## Safety scope

Designed for authorized testing of devices you own or have permission to manage. No jamming, forced disconnections of third-party devices, exploitation, unauthorized access, or private-communication interception. A MAC address is an identifier, not a credential. Pairing and connection require the target device to support the requested profile and may require physical pairing mode or confirmation.

## Requirements

- Kali Linux/Debian, Python 3, Tkinter, BlueZ and a supported Bluetooth adapter.

```bash
sudo apt update
sudo apt install bluez bluetooth rfkill python3 python3-tk git
sudo systemctl enable --now bluetooth
sudo rfkill unblock bluetooth
```

## Run from source

```bash
git clone https://github.com/sajinstalin01/blueguard-bluetooth-scanner.git
cd blueguard-bluetooth-scanner
bash run.sh
```

Select Classic + BLE, Classic, or BLE and start a scan. Select a device row to populate its MAC address or enter a known address in `AA:BB:CC:DD:EE:FF` format. Pair and Connect prompt for authorization confirmation. Some BlueZ pairing flows require additional terminal interaction or physical confirmation on the speaker.

## Update from GitHub

From inside your cloned repository, run:

```bash
bash update.sh
```

The updater fetches the latest `main` branch and uses a fast-forward-only update. It stops if local changes, untracked files, a different branch, or diverged Git history are detected, so it will not silently overwrite your work. After updating, it runs the Python syntax check. Restart the app to use the new version:

```bash
bash run.sh
```

If you downloaded the source as a ZIP rather than cloning with Git, the updater cannot update that folder; clone the repository using the commands above.

## Export

Use the GUI's Export CSV or Export JSON buttons. Exported data includes only information observed by the adapter and BlueZ.

## Build Debian package

Install packaging tools and build dependencies:

```bash
sudo apt install build-essential debhelper dpkg-dev
dpkg-buildpackage -us -uc -b
```

The generated `.deb` appears in the parent directory. Build dependencies include `debhelper-compat (= 13)`.

## Troubleshooting

```bash
bluetoothctl list
bluetoothctl show
rfkill list bluetooth
systemctl status bluetooth --no-pager
journalctl -u bluetooth -n 50 --no-pager
```

If Kali runs in a VM, pass through a compatible USB Bluetooth adapter. Built-in host Bluetooth is not always exposed to the guest. Devices may not advertise continuously; randomized BLE addresses and missing RSSI/name data are normal. Discoverability does not imply vulnerability.
