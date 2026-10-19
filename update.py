#!/usr/bin/env python3
"""Safe terminal updater for BlueGuard Bluetooth Scanner.

Usage:
    python3 update.py
    python3 update.py --check-only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/sajinstalin01/blueguard-bluetooth-scanner.git"
BRANCH = "main"
ROOT = Path(__file__).resolve().parent


def run(args: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=ROOT,
            check=check,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: Required command not found: {args[0]}", file=sys.stderr)
        raise SystemExit(2) from exc
    except subprocess.CalledProcessError as exc:
        if capture and exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        raise


def git(*args: str, capture: bool = False, check: bool = True) -> str:
    result = run(["git", *args], check=check, capture=capture)
    return (result.stdout or "").strip() if capture else ""


def fail(message: str, code: int = 1) -> None:
    print(f"\n[BlueGuard Updater] ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely update BlueGuard from GitHub.")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Fetch GitHub and report whether an update is available without changing local files.",
    )
    args = parser.parse_args()

    print("[BlueGuard Updater] Checking prerequisites...")
    if not (ROOT / "blueguard.py").is_file():
        fail("blueguard.py was not found in this folder.")
    if git("rev-parse", "--is-inside-work-tree", capture=True, check=False) != "true":
        fail(f"This folder is not a Git clone. Clone it with: git clone {REPO_URL}")
    if git("branch", "--show-current", capture=True) != BRANCH:
        fail(f"Switch to the '{BRANCH}' branch before updating.")
    origin = git("remote", "get-url", "origin", capture=True, check=False)
    allowed = {
        REPO_URL,
        "https://github.com/sajinstalin01/blueguard-bluetooth-scanner",
        "git@github.com:sajinstalin01/blueguard-bluetooth-scanner.git",
        "ssh://git@github.com/sajinstalin01/blueguard-bluetooth-scanner.git",
    }
    if origin not in allowed:
        fail(f"Unexpected origin remote: {origin or '(not configured)'}. No changes made.")
    if git("status", "--porcelain", capture=True):
        fail("Local edits or untracked files were found. Commit or back them up first; nothing was overwritten.")

    print("[BlueGuard Updater] Fetching origin/main...")
    run(["git", "fetch", "--prune", "origin", BRANCH])
    local = git("rev-parse", "HEAD", capture=True)
    remote = git("rev-parse", f"origin/{BRANCH}", capture=True)
    if local == remote:
        print("[BlueGuard Updater] Already up to date.")
        return 0

    if args.check_only:
        print("[BlueGuard Updater] An update is available. Re-run without --check-only to install it.")
        return 0

    ancestor = run(
        ["git", "merge-base", "--is-ancestor", "HEAD", f"origin/{BRANCH}"],
        check=False,
    )
    if ancestor.returncode != 0:
        fail("Local and remote histories have diverged. Review Git history manually; no update was applied.")

    print("[BlueGuard Updater] Applying fast-forward-only update...")
    run(["git", "merge", "--ff-only", f"origin/{BRANCH}"])

    print("[BlueGuard Updater] Checking Python syntax...")
    run([sys.executable, "-m", "py_compile", "blueguard.py"])
    print("[BlueGuard Updater] Update complete. Restart the app with: bash run.sh")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        fail(f"Command failed with exit code {exc.returncode}.", exc.returncode or 1)
