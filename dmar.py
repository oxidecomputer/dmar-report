#!/usr/bin/env python3
"""
dmar.py - top-level orchestrator:
  * resolves paths from TOML config, env vars, then hardcoded defaults
  * runs dmar-runner.py (unchanged interface) as a subprocess
  * captures runner output to a log placed next to the CSV
  * finds the results .tar from runner output
  * converts margins+dimms JSON inside that tar into a CSV with PASS/FAIL
  * appends timing and DIMM summary sections to the log

CLI:
    dmar.py <BOOT_JSON> <INVENTRON_NAME> <BRD_SN>
Options:
    --outcsv FILE          (default: <output_root>/<BRD_SN>-run-<YYYYmmdd-%H%M%S>.csv)
    --profile NAME         (overlay settings from [profiles.NAME] in dmar.toml; defaults to INVENTRON_NAME)
    --toml FILE            (path to TOML config file; overrides auto-discovery and DMAR_CONFIG)
    --force                overwrite existing CSV
    --print-config         dump resolved config and exit
    -v/--verbose

Config precedence (highest -> lowest):
    CLI flags > env vars > TOML config > hardcoded defaults

TOML file discovery (highest -> lowest):
    --toml CLI argument > DMAR_CONFIG env var > ./dmar.toml > <script_dir>/dmar.toml >
    <git_root>/dmar.toml > ~/.config/dmar/config.toml > /etc/dmar/config.toml
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import signal
import sys
import tarfile
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

# Global cleanup state
_CLEANUP_DONE = False
_cleanup_state = {'target': None, 'log_path': None}

# ----------------------------
# Config resolution
# ----------------------------

_HARDCODED_DEFAULTS = {
    "image_dir": "/staff/dock/racktest/os/20250924-1735",
    "fw_path": "/staff/tom/git/amd-firmware/BRH/1.0.0.5",
    # tools_path and runner_path default to the runner's directory if not set
    "tools_path": None,
    "runner_path": None,
    # where to place CSV/log by default (current working directory)
    "output_root": ".",
    # pass/fail limits (can be overridden in dmar.toml)
    "eye_height_read_limit": 0.075,
    "eye_height_write_limit": 0.100,
    "eye_width_read_limit": 0.40,
    "eye_width_write_limit": 0.40,
    # dimm expectations (optional)
    "expected_dimms": None,
    "expected_slots": None,
}

_ENV_MAP = {
    "image_dir": "DMAR_IMAGE_DIR",
    "fw_path": "DMAR_FW_PATH",
    "tools_path": "DMAR_TOOLS_DIR",
    "runner_path": "DMAR_RUNNER_PATH",
    "output_root": "DMAR_OUTPUT_ROOT",
    "eye_height_read_limit": "DMAR_EYE_HEIGHT_READ_LIMIT",
    "eye_height_write_limit": "DMAR_EYE_HEIGHT_WRITE_LIMIT",
    "eye_width_read_limit": "DMAR_EYE_WIDTH_READ_LIMIT",
    "eye_width_write_limit": "DMAR_EYE_WIDTH_WRITE_LIMIT",
    "expected_dimms": "DMAR_EXPECTED_DIMMS",
    "expected_slots": "DMAR_EXPECTED_SLOTS",
}

def _parse_env_value(key: str, val: Optional[str]):
    if val is None:
        return None
    if key == "expected_dimms":
        try:
            return int(val)
        except (ValueError, TypeError):
            return None
    if key in (
        "eye_height_read_limit",
        "eye_height_write_limit",
        "eye_width_read_limit",
        "eye_width_write_limit",
    ):
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
    if key == "expected_slots":
        parts = [p.strip() for p in val.split(",") if p.strip()]
        return parts or None
    return val

def _load_toml_config(explicit_path: Optional[str] = None) -> Tuple[dict, Optional[Path]]:
    """Search for a TOML config and return (dict, source_path).

    Args:
        explicit_path: Path from --toml CLI argument (highest priority)
    """
    # import shim
    _have_loader = False
    def _toml_load(_fh):
        raise RuntimeError("no TOML loader")
    try:
        import tomllib  # py311+
        def _toml_load(_fh):  # type: ignore
            return tomllib.load(_fh)
        _have_loader = True
    except Exception:
        try:
            import tomli as _tomli  # py<311
            def _toml_load(_fh):
                return _tomli.load(_fh)
            _have_loader = True
        except Exception:
            pass

    debug = os.environ.get("DMAR_DEBUG_CONFIG") == "1"
    if not _have_loader:
        if debug:
            print("DMAR_DEBUG: No TOML loader available (need Python 3.11+ or install tomli)", file=sys.stderr)
        return {}, None

    candidates: list[Path] = []

    # Highest priority: explicit CLI argument (--toml)
    if explicit_path:
        p = Path(explicit_path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Specified TOML config not found: {explicit_path}")
        candidates.append(p)
        if debug:
            print(f"DMAR_DEBUG: Using explicit --toml path: {p}", file=sys.stderr)

    # Second priority: explicit env override (DMAR_CONFIG)
    env_cfg = os.environ.get("DMAR_CONFIG")
    if env_cfg:
        p = Path(env_cfg).expanduser()
        if p.is_file():
            candidates.append(p)

    # Common locations
    candidates.append(Path.cwd() / "dmar.toml")
    script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir / "dmar.toml")
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True, capture_output=True, text=True
        )
        repo_root = Path(out.stdout.strip())
        if repo_root:
            candidates.append(repo_root / "dmar.toml")
    except Exception:
        pass
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        candidates.append(Path(xdg) / "dmar" / "config.toml")
    else:
        candidates.append(Path.home() / ".config" / "dmar" / "config.toml")
    candidates.append(Path("/etc/dmar/config.toml"))

    first_parse_err: Optional[tuple[Path, Exception]] = None

    if debug:
        print("DMAR_DEBUG: CWD =", Path.cwd(), file=sys.stderr)
        print("DMAR_DEBUG: script_dir =", script_dir, file=sys.stderr)
        print("DMAR_DEBUG: candidate list:", file=sys.stderr)
        for c in candidates:
            print(f"  - {c}  (exists={c.is_file()})", file=sys.stderr)

    for p in candidates:
        try:
            if p.is_file():
                with p.open("rb") as fh:
                    cfg = _toml_load(fh)
                if debug:
                    print(f"DMAR_DEBUG: loaded config from {p}", file=sys.stderr)
                return cfg, p
        except Exception as e:
            if debug:
                print(f"DMAR_DEBUG: parse failed for {p}: {e}", file=sys.stderr)
            if first_parse_err is None:
                first_parse_err = (p, e)
            continue

    # If we saw a file but failed to parse any, surface the first error
    if first_parse_err is not None:
        p, e = first_parse_err
        raise RuntimeError(f"Failed to parse TOML at {p}: {e}")

    if debug:
        print("DMAR_DEBUG: no config file found in any known location", file=sys.stderr)
    return {}, None


def _overlay(dst: dict, src: dict | None) -> dict:
    if not src:
        return dict(dst)
    out = dict(dst)
    for k, v in src.items():
        if v is not None:
            out[k] = v
    return out

def _resolve_config(inventron: str, cli: argparse.Namespace) -> Tuple[dict, Dict[str, Any]]:
    cfg = dict(_HARDCODED_DEFAULTS)

    toml_cfg, cfg_source = _load_toml_config(cli.toml if hasattr(cli, 'toml') else None)
    base_cfg = {
        "image_dir": toml_cfg.get("image_dir"),
        "fw_path": toml_cfg.get("fw_path"),
        "tools_path": toml_cfg.get("tools_path"),
        "runner_path": toml_cfg.get("runner_path"),
        "output_root": toml_cfg.get("output_root"),
        "eye_height_read_limit": toml_cfg.get("eye_height_read_limit"),
        "eye_height_write_limit": toml_cfg.get("eye_height_write_limit"),
        "eye_width_read_limit": toml_cfg.get("eye_width_read_limit"),
        "eye_width_write_limit": toml_cfg.get("eye_width_write_limit"),
        "expected_dimms": toml_cfg.get("expected_dimms"),
        "expected_slots": toml_cfg.get("expected_slots"),
    }
    cfg = _overlay(cfg, base_cfg)

    profile_name = cli.profile or inventron
    profiles = toml_cfg.get("profiles") or {}
    profile_cfg = profiles.get(profile_name) or {}
    cfg = _overlay(cfg, {
        "image_dir": profile_cfg.get("image_dir"),
        "fw_path": profile_cfg.get("fw_path"),
        "tools_path": profile_cfg.get("tools_path"),
        "runner_path": profile_cfg.get("runner_path"),
        "output_root": profile_cfg.get("output_root"),
        "eye_height_read_limit": profile_cfg.get("eye_height_read_limit"),
        "eye_height_write_limit": profile_cfg.get("eye_height_write_limit"),
        "eye_width_read_limit": profile_cfg.get("eye_width_read_limit"),
        "eye_width_write_limit": profile_cfg.get("eye_width_write_limit"),
        "expected_dimms": profile_cfg.get("expected_dimms"),
        "expected_slots": profile_cfg.get("expected_slots"),
    })

    env_overlay = {}
    for k, envk in _ENV_MAP.items():
        env_val = os.environ.get(envk)
        env_overlay[k] = _parse_env_value(k, env_val)
    cfg = _overlay(cfg, env_overlay)

    cli_overlay = {
        "image_dir": cli.image_dir,
        "fw_path": cli.fw_path,
        "tools_path": cli.tools_path,
        "runner_path": cli.runner_path,
        "output_root": cli.output_root,
    }
    cfg = _overlay(cfg, cli_overlay)

    script_dir = Path(__file__).resolve().parent
    if not cfg.get("runner_path"):
        cfg["runner_path"] = str(script_dir / "dmar-runner.py")
    if not cfg.get("tools_path"):
        cfg["tools_path"] = str(Path(cfg["runner_path"]).resolve().parent)

    for k in ("image_dir", "fw_path", "tools_path", "output_root", "runner_path"):
        v = cfg.get(k)
        if isinstance(v, str):
            cfg[k] = str(Path(v).expanduser())

    meta = {
        "config_source": str(cfg_source) if cfg_source else None,
        "profile_used": profile_name,
    }
    return cfg, meta

# ----------------------------
# CSV conversion
# ----------------------------

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
                            row.extend([m_rw_s, m_rh_s, m_ww_s, m_wh_s, "PASS" if pass_ok else "FAIL"])
                            w.writerow(row)

    return dimm_list_for_summary

def csv_from_tar(tar_path: Path, out_csv: Path, brd_sn: Optional[str], limits: dict):
    margins = _find_json_in_tar(str(tar_path), "margins.json")
    dimms   = _find_json_in_tar(str(tar_path), "dimms.json")
    dimm_list = _write_csv_from_json(margins, dimms, out_csv, brd_sn, limits)
    return dimm_list

# ----------------------------
# Runner orchestration and timing
# ----------------------------

RUNNER_RESULT_RE = re.compile(r"^DRAM Margining Test Results:\s*(?P<tar>\S+\.tar)\s*$")

def default_csv_path(output_root: Path, brd_sn: str, run_start_dt: datetime) -> Path:
    ts = run_start_dt.strftime("%Y%m%d-%H%M%S")
    return output_root / f"{brd_sn}-run-{ts}.csv"

def resolve_runner_path(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if p.is_dir():
        cand = p / "dmar-runner.py"
    else:
        cand = p
    cand = cand.resolve()
    if not cand.exists() or not cand.is_file():
        raise FileNotFoundError(
            f"dmar-runner.py not found at '{path_str}'. "
            f"Provide runner_path as the file itself or a directory containing dmar-runner.py."
        )
    return cand

def run_runner_and_capture(image_dir: str, boot_json: str, inventron: str,
                           fw_path: str, tools_path: str, runner_path: str,
                           log_path: Path, verbose: bool):
    """
    Spawn dmar-runner.py and tee its output to console + log.
    Returns (exit_code, tar_path or None, timings dict).
    timings keys: qspi_start, qspi_end, boot_start, boot_to_x86, phase2_served,
                  boot_complete, report_start, report_done, run_start, run_end.
    """
    runner_file = resolve_runner_path(runner_path)

    cmd = [
        sys.executable, "-u", str(runner_file),
        image_dir, boot_json, f"{inventron}-sp",
        "-e", inventron,
        "--fw-path", fw_path,
        "--tools-path", tools_path,
    ]
    if verbose:
        cmd.append("-v")

    timings: Dict[str, datetime] = {}
    timings["run_start"] = datetime.now()

    tar_candidate: Optional[Path] = None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", buffering=1) as lf:
        lf.write(f"Script started at: {timings['run_start'].isoformat()}\n")
        lf.write(f"CMD: {' '.join(cmd)}\n")
        lf.flush()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                lf.write(line)
                s = line.strip()
                if "Writing image to target..." in s and "qspi_start" not in timings:
                    timings["qspi_start"] = datetime.now()
                elif "Starting testing..." in s:
                    now = datetime.now()
                    if "qspi_start" in timings and "qspi_end" not in timings:
                        timings["qspi_end"] = now
                    timings["boot_start"] = timings.get("boot_start", now)
                elif s.startswith("Oxide Pico Host Boot Loader") or s.startswith("Booted to x86"):
                    timings["boot_to_x86"] = datetime.now()
                elif re.match(r"^Waiting for .* to boot\.\.\.", s):
                    timings["phase2_served"] = datetime.now()
                elif s.startswith("Begin DRAM Margining results collection"):
                    now = datetime.now()
                    timings["boot_complete"] = timings.get("boot_complete", now)
                    timings["report_start"] = now
                else:
                    m = RUNNER_RESULT_RE.match(s)
                    if m:
                        timings["report_done"] = datetime.now()
                        tar_text = m.group("tar")
                        tar_candidate = Path(tar_text).resolve()
        finally:
            proc.wait()
            timings["run_end"] = datetime.now()
            code = proc.returncode
            lf.write(f"Exit code: {code}\n")
            lf.write(f"Script ended at: {timings['run_end'].isoformat()}\n")
    return code, tar_candidate, timings

def _fmt_duration(start: Optional[datetime], end: Optional[datetime]) -> str:
    if not start or not end:
        return "n/a"
    delta = end - start
    total_sec = int(delta.total_seconds())
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def append_timing_summary(log_path: Path, t: Dict[str, datetime]):
    lines = []
    lines.append("==== Timing Summary ====\n")
    lines.append(f"QSPI write:        {_fmt_duration(t.get('qspi_start'), t.get('qspi_end'))}\n")
    lines.append(f"Boot to x86:       {_fmt_duration(t.get('boot_start'), t.get('boot_to_x86'))}\n")
    lines.append(f"Boot complete:     {_fmt_duration(t.get('boot_start'), t.get('boot_complete'))}\n")
    lines.append(f"Report runtime:    {_fmt_duration(t.get('report_start'), t.get('report_done'))}\n")
    lines.append(f"Total runtime:     {_fmt_duration(t.get('run_start'), t.get('run_end'))}\n")
    with log_path.open("a") as lf:
        lf.write("\n")
        for ln in lines:
            lf.write(ln)

def append_dimm_summary(log_path: Path, brd_sn: str, dimm_list: list, expected_dimms: Optional[int], expected_slots: Optional[list]):
    lines = []
    lines.append("==== DIMM Summary ====\n")
    lines.append(f"Target serial: {brd_sn}\n")
    count = len(dimm_list)
    lines.append(f"DIMMs present: {count}\n")
    if expected_dimms is not None and count < int(expected_dimms):
        lines.append(f"warning: {expected_dimms} dimms expected, only {count} dimms found\n")
    seen_slots = []
    for chan, slot, mfg, pn, sn in dimm_list:
        lines.append(f"  - Channel {chan}, Slot {slot}, MFG {mfg}, PN {pn}, SN {sn}\n")
        if slot:
            seen_slots.append(str(slot))
    if expected_slots:
        missing = [s for s in expected_slots if s not in seen_slots]
        if missing:
            lines.append("SLOT not found:\n")
            lines.append("  " + " ".join(missing) + "\n")
    with log_path.open("a") as lf:
        lf.write("\n")
        for ln in lines:
            lf.write(ln)

# ----------------------------
# CLI
# ----------------------------

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run DMAR, capture results tar, and emit CSV with PASS/FAIL.")
    ap.add_argument("boot_json", help="Path to boot JSON (same as dmar.sh)")
    ap.add_argument("inventron", help="Inventron environment name (e.g., mb-3)")
    ap.add_argument("brd_sn", help="Board serial number (e.g., BRM13250005)")
    ap.add_argument("--image-dir", help="(override) Image directory")
    ap.add_argument("--fw-path", help="(override) Firmware blobs path")
    ap.add_argument("--tools-path", help="(override) Directory containing required tools")
    ap.add_argument("--runner-path", help="(override) Path to dmar-runner.py (file or directory)")
    ap.add_argument("--output-root", help="(override) Root directory for CSV and log")
    ap.add_argument("--outcsv", help="Output CSV path (default uses output_root/brd_sn/date)")
    ap.add_argument("--profile", help="Profile name from dmar.toml [profiles.<name>] (defaults to INVENTRON)")
    ap.add_argument("--toml", help="Path to TOML config file (overrides auto-discovery and DMAR_CONFIG)")
    ap.add_argument("--force", action="store_true", help="Overwrite existing CSV")
    ap.add_argument("--print-config", action="store_true", help="Print resolved config and exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def cleanup_target(target: str, log_path: Path):
    """Restore flash device to Flash0, clear boot startup options, and reset console UART redirect."""
    global _CLEANUP_DONE

    if _CLEANUP_DONE:
        return  # Cleanup already executed, skip to prevent double-execution

    _CLEANUP_DONE = True

    # Ensure log directory exists before writing
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        pass  # Continue cleanup even if log directory creation fails

    cmds = [
        ['pfexec', 'humility', '-t', target, 'hiffy', '-c', 'HostFlash.set_dev', '-a', 'dev=Flash0'],
        ['pfexec', 'humility', '-t', target, 'hiffy', '-c', 'ControlPlaneAgent.set_startup_options', '-a', 'startup_options=0x0'],
        ['pfexec', 'humility', '-t', target, 'hiffy', '-c', 'FmcDemo.poke32', '-a', 'addr=0x60000700,value=0x0'],
    ]
    try:
        with log_path.open("a") as lf:
            lf.write("\n==== Cleanup ====\n")
    except (OSError, IOError):
        pass  # Continue cleanup even if logging fails
    for cmd in cmds:
        try:
            res = subprocess.run(cmd, check=True, capture_output=True, text=True)
            try:
                with log_path.open("a") as lf:
                    lf.write(f"$ {' '.join(cmd)}\n")
                    if res.stdout:
                        lf.write(res.stdout)
                    if res.stderr:
                        lf.write(res.stderr)
            except (OSError, IOError):
                pass  # Continue cleanup even if logging fails
        except subprocess.CalledProcessError as e:
            # Warn user about cleanup failure - hardware may be in unexpected state
            error_msg = f"WARNING: Cleanup command failed (exit {e.returncode}): {' '.join(cmd)}"
            print(error_msg, file=sys.stderr)
            if e.stderr:
                print(f"  Error output: {e.stderr.strip()}", file=sys.stderr)

            try:
                with log_path.open("a") as lf:
                    lf.write(f"$ {' '.join(cmd)}\n")
                    lf.write(f"ERROR: exit {e.returncode}\n")
                    if e.stdout:
                        lf.write(e.stdout)
                    if e.stderr:
                        lf.write(e.stderr)
            except (OSError, IOError):
                pass  # Continue cleanup even if logging fails


def signal_handler(signum, frame):
    """Handle SIGINT and SIGTERM to ensure cleanup happens on interrupt."""
    print(f"\nReceived signal {signum}, cleaning up...", file=sys.stderr)

    if _cleanup_state['target'] and _cleanup_state['log_path']:
        try:
            cleanup_target(_cleanup_state['target'], _cleanup_state['log_path'])
        except (OSError, subprocess.SubprocessError) as e:
            print(f"WARNING: Cleanup failed during interrupt: {e}", file=sys.stderr)
            print("Hardware may be in unexpected state - manual cleanup may be required", file=sys.stderr)

    sys.exit(128 + signum)


def clean_then_exit(exit_code: int, target: str, log_path: Path, msg: Optional[str] = None):
    """
    Perform cleanup routine and exit with specified code.

    Args:
        exit_code: Exit code to return
        target: Target name (e.g., 'mb-3-sp')
        log_path: Path to log file for cleanup logging
        msg: Optional message to print before cleanup
    """
    if msg:
        print(msg, file=sys.stderr)

    # Ensure log directory exists before cleanup
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        cleanup_target(target, log_path)
    except (OSError, subprocess.SubprocessError) as e:
        error_msg = f"\nWarning: cleanup failed: {e}\n"
        print(error_msg.strip(), file=sys.stderr)
        # Try to log to file if possible
        try:
            if log_path.parent.exists():
                with log_path.open("a") as lf:
                    lf.write(error_msg)
        except (OSError, IOError):
            pass  # Can't log to file, already printed to stderr

    sys.exit(exit_code)

def main():
    args = _build_parser().parse_args()
    cfg, meta = _resolve_config(args.inventron, args)


    if args.print_config:
        print("Resolved configuration:")
        for k in ("image_dir", "fw_path", "tools_path", "runner_path", "output_root"):
            print(f"  {k}: {cfg.get(k)}")
        print(f"  eye_height_read_limit:  {cfg.get('eye_height_read_limit')}")
        print(f"  eye_height_write_limit: {cfg.get('eye_height_write_limit')}")
        print(f"  eye_width_read_limit:   {cfg.get('eye_width_read_limit')}")
        print(f"  eye_width_write_limit:  {cfg.get('eye_width_write_limit')}")
        print(f"  expected_dimms:         {cfg.get('expected_dimms')}")
        print(f"  expected_slots:         {cfg.get('expected_slots')}")
        print(f"Config source: {meta.get('config_source')}")
        print(f"Profile used:  {meta.get('profile_used')}")
        # extra context
        print(f"CWD:          {Path.cwd()}")
        print(f"Script dir:   {Path(__file__).resolve().parent}")
        sys.exit(0)

    run_start = datetime.now()

    if args.outcsv:
        out_csv = Path(args.outcsv).expanduser().resolve()
        out_dir = out_csv.parent
    else:
        out_dir = Path(cfg["output_root"]).expanduser().resolve()
        out_csv = default_csv_path(out_dir, args.brd_sn, run_start).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = run_start.strftime("%Y%m%d.%H%M%S")
    log_path  = out_dir / f"dmar.{args.brd_sn}.{timestamp}.log"

    # Set cleanup state before registering signal handlers to avoid race condition
    _cleanup_state['target'] = f"{args.inventron}-sp"
    _cleanup_state['log_path'] = log_path

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    code, tar_path, timings = run_runner_and_capture(
        image_dir=cfg["image_dir"],
        boot_json=args.boot_json,
        inventron=args.inventron,
        fw_path=cfg["fw_path"],
        tools_path=cfg["tools_path"],
        runner_path=cfg["runner_path"],
        log_path=log_path,
        verbose=args.verbose,
    )

    if code != 0:
        clean_then_exit(code, f"{args.inventron}-sp", log_path, f"Runner failed (exit {code}). See {log_path}")

    if tar_path is None or not tar_path.exists():
        candidates = sorted(Path(".").glob("*.tar"), key=lambda p: p.stat().st_mtime, reverse=True)
        tar_path = candidates[0] if candidates else None

    if tar_path is None or not tar_path.exists():
        clean_then_exit(2, f"{args.inventron}-sp", log_path, "Error: Results .tar not found. Check the log for the results line.")

    if out_csv.exists() and not args.force:
        # Resolve naming conflict by appending timestamp
        stem = out_csv.stem
        suffix = out_csv.suffix
        conflict_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_csv = out_csv.parent / f"{stem}_{conflict_ts}{suffix}"
        print(f"Warning: CSV exists, writing to {out_csv} instead", file=sys.stderr)

    limits = {
        "eye_height_read_limit": float(cfg["eye_height_read_limit"]),
        "eye_height_write_limit": float(cfg["eye_height_write_limit"]),
        "eye_width_read_limit": float(cfg["eye_width_read_limit"]),
        "eye_width_write_limit": float(cfg["eye_width_write_limit"]),
    }

    try:
        dimm_list = csv_from_tar(tar_path, out_csv, args.brd_sn, limits)
    except Exception as e:
        clean_then_exit(4, f"{args.inventron}-sp", log_path, f"CSV conversion failed: {e}")

    try:
        append_timing_summary(log_path, timings)
        expected_dimms = cfg.get("expected_dimms")
        expected_slots = cfg.get("expected_slots")
        append_dimm_summary(log_path, args.brd_sn, dimm_list, expected_dimms, expected_slots)
    except Exception as e:
        with log_path.open("a") as lf:
            lf.write(f"\nWarning: failed to append summaries: {e}\n")

    print(f"CSV written to {out_csv}")
    print(f"Log saved to {log_path}")
    # Restore target state (Flash0 and boot options 0x0)
    try:
        cleanup_target(f"{args.inventron}-sp", log_path)
    except Exception as e:
        with log_path.open("a") as lf:
            lf.write(f"\nWarning: cleanup failed: {e}\n")
    sys.exit(0)

if __name__ == "__main__":
    main()

