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
from typing import Optional
import json
import tarfile
import csv

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

# ----------------------------
# CSV conversion
# ----------------------------

def _safe_float(x):
    try:
        return float(x)
    except (ValueError, TypeError):
        return None

def _fmt4(x):
    """Format as float with 4 decimals; keep empty if missing."""
    try:
        return f"{float(x):.4f}"
    except (ValueError, TypeError):
        return "" if x in (None, "") else str(x)

def _find_json_in_tar(tarfilename: str, json_basename: str):
    with tarfile.open(tarfilename, "r:*") as tar:
        target = None
        for m in tar.getmembers():
            name = m.name
            if name.endswith("/" + json_basename) or name == json_basename or name.lower().endswith("/" + json_basename.lower()):
                target = m
                break
        if target is None:
            for m in tar.getmembers():
                if Path(m.name).name.lower() == json_basename.lower():
                    target = m
                    break
        if target is None:
            raise FileNotFoundError(f"{json_basename} not found in {tarfilename}")
        f = tar.extractfile(target)
        if f is None:
            raise IOError(f"Could not extract {json_basename} from {tarfilename}")
        return json.load(f)

def _write_csv_from_json(margins, dimms, output_path: Path, brd_sn: Optional[str], limits: dict):
    dimm_info_map = {}
    dimm_list_for_summary = []
    if isinstance(dimms, list):
        for entry in dimms:
            chan = entry.get("chan")
            slot = entry.get("slot", "")
            dd = entry.get("dimms", {})
            if isinstance(dd, dict):
                for k, v in dd.items():
                    if not isinstance(v, dict):
                        continue
                    dimm_list_for_summary.append((chan, slot, v.get("module_mfg",""), v.get("part_number",""), v.get("serial_number","")))
                d0 = dd.get("0", {})
            else:
                d0 = {}
            if chan is None:
                continue
            dimm_info_map[chan] = {
                "PCB_CH": slot,
                "DIMM_MFG": d0.get("module_mfg", ""),
                "DIMM_PN": d0.get("part_number", ""),
                "DIMM_SN": d0.get("serial_number", ""),
            }


    headers = [
        "Soc_Chan", "PCB_Chan", "CS", "SC", "Lane",
        "Read Width (UI)", "Read Height (V)", "Write Width (UI)", "Write Height (V)",
        "DIMM_MFG", "DIMM_PN", "DIMM_SN",
    ]
    if brd_sn:
        headers.append("Board SN")
    headers.append("Speed")  # Add speed column before margin calculations
    headers += [
        "margin_read_width", "margin_read_height", "margin_write_width", "margin_write_height",
        "PASS",  # PASS is last column
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as fout:
        w = csv.writer(fout)
        w.writerow(headers)

        if not isinstance(margins, list):
            raise ValueError("margins.json has unexpected structure (expected a list)")

        for m in margins:
            soc_chan = m.get("chan")
            speed = m.get("speed") or ""  # Extract speed from channel data, convert None to empty string
            pcb_info = dimm_info_map.get(soc_chan, {})
            pcb_chan = pcb_info.get("PCB_CH", "")
            dimm_mfg = pcb_info.get("DIMM_MFG", "")
            dimm_pn  = pcb_info.get("DIMM_PN",  "")
            dimm_sn  = pcb_info.get("DIMM_SN",  "")

            dimms_field = m.get("dimms", {})
            if not isinstance(dimms_field, dict):
                continue

            for _dimm_num, dimm_data in dimms_field.items():
                ranks = dimm_data.get("ranks", {})
                if not isinstance(ranks, dict):
                    continue
                for cs, rank_val in ranks.items():
                    sub_chans = rank_val.get("sub_chans", {})
                    if isinstance(sub_chans, dict):
                        subch_iter = sub_chans.items()
                    elif isinstance(sub_chans, list):
                        subch_iter = enumerate(sub_chans)
                    else:
                        continue
                    for sc, sc_val in subch_iter:
                        data_eyes = sc_val.get("data_eyes", {})
                        if isinstance(data_eyes, dict):
                            lane_iter = data_eyes.items()
                        elif isinstance(data_eyes, list):
                            lane_iter = enumerate(data_eyes)
                        else:
                            continue
                        for lane, lane_val in lane_iter:
                            read  = lane_val.get("read",  ["", ""])
                            write = lane_val.get("write", ["", ""])

                            rw = _safe_float(read[0])
                            rh = _safe_float(read[1])
                            ww = _safe_float(write[0])
                            wh = _safe_float(write[1])

                            # printable values for widths/heights
                            rw_s = _fmt4(rw if rw is not None else read[0])
                            rh_s = _fmt4(rh if rh is not None else read[1])
                            ww_s = _fmt4(ww if ww is not None else write[0])
                            wh_s = _fmt4(wh if wh is not None else write[1])

                            m_rw = "" if rw is None else (rw - limits["eye_width_read_limit"])
                            m_rh = "" if rh is None else (rh - limits["eye_height_read_limit"])
                            m_ww = "" if ww is None else (ww - limits["eye_width_write_limit"])
                            m_wh = "" if wh is None else (wh - limits["eye_height_write_limit"])
                            m_rw_s = _fmt4(m_rw)
                            m_rh_s = _fmt4(m_rh)
                            m_ww_s = _fmt4(m_ww)
                            m_wh_s = _fmt4(m_wh)

                            pass_ok = (
                                rw is not None and rh is not None and ww is not None and wh is not None
                                and rw >= limits["eye_width_read_limit"]
                                and rh >= limits["eye_height_read_limit"]
                                and ww >= limits["eye_width_write_limit"]
                                and wh >= limits["eye_height_write_limit"]
                            )

                            row = [
                            soc_chan, pcb_chan, cs, sc, lane,
                            rw_s, rh_s, ww_s, wh_s,
                            dimm_mfg, dimm_pn, dimm_sn,
                            ]
                            if brd_sn:
                                row.append(brd_sn)
                            row.append(speed)  # Add speed value to the row
                            row.extend([m_rw_s, m_rh_s, m_ww_s, m_wh_s, "PASS" if pass_ok else "FAIL"])
                            w.writerow(row)

    return dimm_list_for_summary


def csv_from_tar(tar_path: Path, out_csv: Path, brd_sn: Optional[str], limits: dict):
    margins = _find_json_in_tar(str(tar_path), "margins.json")
    dimms   = _find_json_in_tar(str(tar_path), "dimms.json")
    dimm_list = _write_csv_from_json(margins, dimms, out_csv, brd_sn, limits)
    return dimm_list

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
        dimm_list = csv_from_tar(tar_path, out_csv, brd_sn, limits)
        slot_list = sorted(set([slot for (_, slot, _, _, _) in dimm_list]))
        print(f"DIMM Count: {len(dimm_list)}")
        print(f"Slots: {', '.join(slot_list)}")
    except Exception as e:
        print(f"conversion failed: {e}", file=sys.stderr)
        sys.exit(4)

    print(f"CSV written: {out_csv}")

if __name__ == "__main__":
    main()

