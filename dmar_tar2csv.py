#!/usr/bin/env python3
"""
dmar_tar2csv.py

Generate a DMAR CSV directly from a results .tar using ONLY limits from a TOML.
If any required limit is missing, the script exits with an error.

Usage:
    dmar_tar2csv.py --in-tar <tarfile> --out-csv <csv> --toml <config.toml> [--profile NAME]

Notes:
- Reuses dmar.csv_from_tar(...) so CSV layout and PASS/FAIL logic match dmar.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import dmar  # reuses csv_from_tar

REQUIRED_LIMIT_KEYS = (
    "eye_height_read_limit",
    "eye_height_write_limit",
    "eye_width_read_limit",
    "eye_width_write_limit",
)

def _load_toml(path: Path) -> dict:
    """Load TOML using tomllib (py311+) or tomli."""
    err = None
    try:
        import tomllib  # Python 3.11+
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except Exception as e:
        err = e
    try:
        import tomli
        with path.open("rb") as fh:
            return tomli.load(fh)
    except Exception as e2:
        raise RuntimeError(
            f"Cannot parse TOML at {path}. Use Python 3.11+ or install 'tomli'. "
            f"(tomllib error: {err}; tomli error: {e2})"
        )

def _strict_limits_from_toml(tcfg: dict, profile: str | None) -> dict:
    """
    Build the final limits dict strictly from TOML (plus optional [profiles.NAME]).
    Error if any required key is missing or null after overlay.
    """
    # Start from top-level keys
    limits = {k: tcfg.get(k) for k in REQUIRED_LIMIT_KEYS}

    # Overlay profile section if requested
    if profile:
        psec = (tcfg.get("profiles") or {}).get(profile) or {}
        for k in REQUIRED_LIMIT_KEYS:
            if k in psec and psec[k] is not None:
                limits[k] = psec[k]

    # Validate presence and type
    missing = [k for k, v in limits.items() if v is None]
    if missing:
        raise ValueError(
            "Missing required limit(s) in TOML"
            + (f" (profile '{profile}')" if profile else "")
            + f": {', '.join(missing)}"
        )

    # Coerce to float and validate
    parsed = {}
    bad = []
    for k, v in limits.items():
        try:
            parsed[k] = float(v)
        except Exception:
            bad.append(k)
    if bad:
        raise ValueError(
            "Non-numeric limit value(s) in TOML"
            + (f" (profile '{profile}')" if profile else "")
            + f": {', '.join(bad)}"
        )

    return parsed

def main():
    ap = argparse.ArgumentParser(
        description="Convert a DMAR results .tar to CSV using STRICT limits from a TOML."
    )
    ap.add_argument("--in-tar", required=True, help="Path to results .tar")
    ap.add_argument("--out-csv", required=True, help="Output CSV path")
    ap.add_argument("--toml", required=True, help="Path to TOML providing limit keys")
    ap.add_argument("--profile", help="Optional [profiles.<name>] overlay from the TOML")
    args = ap.parse_args()

    tar_path = Path(args.in_tar).expanduser().resolve()
    out_csv = Path(args.out_csv).expanduser().resolve()
    toml_p = Path(args.toml).expanduser().resolve()

    if not tar_path.is_file():
        print(f"error: input tar not found: {tar_path}", file=sys.stderr)
        sys.exit(2)
    if not toml_p.is_file():
        print(f"error: TOML config not found: {toml_p}", file=sys.stderr)
        sys.exit(2)

    out_csv.parent.mkdir(parents=True, exist_ok=True)

    try:
        tcfg = _load_toml(toml_p)
        limits = _strict_limits_from_toml(tcfg, args.profile)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(3)

    # Board SN is optional here; pass None unless you want to add a filename parser.
    brd_sn = None

    try:
        dmar.csv_from_tar(tar_path, out_csv, brd_sn, limits)
    except Exception as e:
        print(f"conversion failed: {e}", file=sys.stderr)
        sys.exit(4)

    print(f"CSV written: {out_csv}")

if __name__ == "__main__":
    main()

