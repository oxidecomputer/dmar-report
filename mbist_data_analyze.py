#!/usr/bin/env python3
# See chat for usage: mbist_analyze.py 'BRM*.csv' --outdir out --plots-per-channel --limit-channels 12
import os, glob, argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from collections import defaultdict
import toml
from tabulate import tabulate

# Default eye margin limits (can be overridden by TOML file if present)
DEFAULT_LIMITS = {
    "ReadHeight_V": 0.075,
    "ReadWidth_UI": 0.40,
    "WriteHeight_V": 0.100,
    "WriteWidth_UI": 0.40,
}

CANON_COLS = {
    "soc_chan": ["soc_chan", "soc_channel", "soc_chn", "soc"],
    "pcb_chan": ["pcb_chan", "pcb_channel", "pcb_chn", "channel", "chan"],
    "cs": ["cs", "chip_select"],
    "sc": ["sc", "subch", "sub_channel", "subchan", "sub_channel_index"],
    "lane": ["lane", "bit", "dq", "dq_lane"],
    "rw_ui": ["read width (ui)", "read_width_ui", "read_width", "read ui", "read width ui"],
    "rh_v": ["read height (v)", "read_height_v", "read_height", "read v", "read height v"],
    "ww_ui": ["write width (ui)", "write_width_ui", "write_width", "write ui", "write width ui"],
    "wh_v": ["write height (v)", "write_height_v", "write_height", "write v", "write height v"],
    "dimm_mfg": ["dimm_mfg", "dimm mfg", "mfg", "vendor"],
    "dimm_pn": ["dimm_pn", "dimm pn", "pn", "part", "partnumber", "part_number"],
    "dimm_sn": ["dimm_sn", "dimm sn", "serial", "serial_number"],
    "board_sn": ["board_sn", "board sn", "board_serial", "board_serial_number"],
}

def find_col(df, candidates):
    normalized = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        if cand in normalized:
            return normalized[cand]
    import re
    relaxed = {re.sub(r"[^a-z0-9]", "", c.lower()): c for c in df.columns}
    for cand in candidates:
        key = re.sub(r"[^a-z0-9]", "", cand.lower())
        if key in relaxed:
            return relaxed[key]
    return None

alpha_map = {c:i for i,c in enumerate(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))}

def to_channel(series):
    """Convert channel to numeric, handling both numbers and letters"""
    num = pd.to_numeric(series, errors="coerce")
    s = series.astype(str).str.strip().str.upper().str[0]
    mapped = s.map(alpha_map)
    return num.fillna(mapped)

def to_channel_str(series):
    """Convert channel to string representation (preserves letters like A,B,C)"""
    # First try numeric conversion
    num = pd.to_numeric(series, errors="coerce")
    # For non-numeric, extract first character and uppercase
    s = series.astype(str).str.strip().str.upper().str[0]
    # Return string version: use letter if available, otherwise the number
    result = series.astype(str).str.strip().str.upper()
    # Clean up to just first char/letter for consistency
    return result.str[0]

def load_and_normalize(path):
    df = pd.read_csv(path)
    mapping = {k: find_col(df, v) for k, v in CANON_COLS.items()}
    if mapping["pcb_chan"] is None and mapping["soc_chan"] is None:
        raise ValueError(f"Neither PCB_Chan nor Soc_Chan present in {path}")
    out = pd.DataFrame()

    # Numeric conversion for sorting/grouping
    pcb_num = to_channel(df[mapping["pcb_chan"]]) if mapping["pcb_chan"] else None
    soc_num = to_channel(df[mapping["soc_chan"]]) if mapping["soc_chan"] else None

    # String conversion to preserve PCB channel names (like A, B, C)
    pcb_str = to_channel_str(df[mapping["pcb_chan"]]) if mapping["pcb_chan"] else None
    soc_str = to_channel_str(df[mapping["soc_chan"]]) if mapping["soc_chan"] else None

    # Use PCB for primary channel if available, otherwise SOC
    chan_num = pcb_num if pcb_num is not None else soc_num

    # Create combined channel name: "SOC-PCB" (e.g., "0-C")
    if soc_str is not None and pcb_str is not None:
        out["Channel"] = soc_str.astype(str) + "-" + pcb_str.astype(str)
    elif pcb_str is not None:
        out["Channel"] = pcb_str.astype(str)
    else:
        out["Channel"] = soc_str.astype(str)

    # Keep numeric version for sorting (use SOC channel for primary sort)
    out["Chan_Sort"] = soc_num if soc_num is not None else chan_num

    out["CS"] = pd.to_numeric(df[mapping["cs"]], errors="coerce")
    out["SC"] = pd.to_numeric(df[mapping["sc"]], errors="coerce")
    out["Lane"] = pd.to_numeric(df[mapping["lane"]], errors="coerce")
    out["LaneIdx"] = out["Lane"] + 40*out["SC"]
    out["ReadWidth_UI"] = pd.to_numeric(df[mapping["rw_ui"]], errors="coerce")
    out["ReadHeight_V"] = pd.to_numeric(df[mapping["rh_v"]], errors="coerce")
    out["WriteWidth_UI"] = pd.to_numeric(df[mapping["ww_ui"]], errors="coerce")
    out["WriteHeight_V"] = pd.to_numeric(df[mapping["wh_v"]], errors="coerce")
    out["DIMM_MFG"] = df[mapping["dimm_mfg"]].astype(str) if mapping["dimm_mfg"] else ""
    out["DIMM_PN"] = df[mapping["dimm_pn"]].astype(str) if mapping["dimm_pn"] else ""
    if mapping["dimm_sn"]:
        out["DIMM_SN"] = df[mapping["dimm_sn"]].astype(str)
    if mapping["board_sn"]:
        out["Board_SN"] = df[mapping["board_sn"]].astype(str)
    out["SourceFile"] = os.path.basename(path)
    out = out.dropna(subset=["Chan_Sort","CS","SC","Lane"])
    out["Chan_Sort"] = out["Chan_Sort"].astype(int)
    out["CS"] = out["CS"].astype(int)
    out["SC"] = out["SC"].astype(int)
    out["Lane"] = out["Lane"].astype(int)
    out["LaneIdx"] = out["LaneIdx"].astype(int)
    return out

def stack_inputs(patterns):
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    if not files:
        raise FileNotFoundError(f"No files match: {patterns}")

    print(f"Processing {len(files)} CSV file(s):")
    for f in files:
        print(f"  - {f}")
    print()

    frames = [load_and_normalize(f) for f in files]
    return pd.concat(frames, ignore_index=True)

def stats_by(df, keys):
    """Calculate statistics grouped by specified keys"""
    metrics = ["ReadWidth_UI","ReadHeight_V","WriteWidth_UI","WriteHeight_V"]
    agg = {m: ["min","max","mean","std","count"] for m in metrics}
    g = df.groupby(keys).agg(agg)
    g.columns = [f"{m}_{stat}" for m, stat in g.columns]
    result = g.reset_index()

    # Sort by Chan_Sort if present in keys for proper ordering
    if "Chan_Sort" in keys:
        result = result.sort_values("Chan_Sort")
        # Drop Chan_Sort from output - it's only for sorting
        result = result.drop(columns=["Chan_Sort"])

    return result

def load_limits(limits_file="dmar.toml"):
    """Load pass/fail limits from TOML file, falling back to defaults"""
    # Start with default limits
    limits = DEFAULT_LIMITS.copy()

    # Try to load from TOML file if it exists
    if os.path.exists(limits_file):
        try:
            config = toml.load(limits_file)
            # Override defaults with TOML values if present
            if "eye_height_read_limit" in config:
                limits["ReadHeight_V"] = config["eye_height_read_limit"]
            if "eye_width_read_limit" in config:
                limits["ReadWidth_UI"] = config["eye_width_read_limit"]
            if "eye_height_write_limit" in config:
                limits["WriteHeight_V"] = config["eye_height_write_limit"]
            if "eye_width_write_limit" in config:
                limits["WriteWidth_UI"] = config["eye_width_write_limit"]
        except Exception as e:
            print(f"Warning: Could not load limits from {limits_file}: {e}")
            print(f"Using default limits instead.")

    return limits

def identify_low_spots(df, limits=None, threshold_factor=2.0):
    """Identify lanes with significantly lower performance than average"""
    metrics = ["ReadWidth_UI","ReadHeight_V","WriteWidth_UI","WriteHeight_V"]
    outliers = []

    for metric in metrics:
        data = df[metric].dropna()
        if len(data) == 0:
            continue
        mu = data.mean()
        sd = data.std()

        # Flag values below mean - threshold_factor*std
        low_threshold = mu - threshold_factor * sd

        # Also check against absolute limits if provided
        if limits and limits.get(metric):
            low_threshold = max(low_threshold, limits[metric])

        low_mask = df[metric] < low_threshold
        cols_to_include = ["Channel", "CS", "SC", "Lane", "LaneIdx", metric, "DIMM_MFG", "DIMM_PN"]
        if "DIMM_SN" in df.columns:
            cols_to_include.append("DIMM_SN")
        low_data = df[low_mask][cols_to_include].copy()

        if not low_data.empty:
            low_data["Metric"] = metric
            low_data["Threshold"] = low_threshold
            low_data["Mean"] = mu
            low_data["StdDev"] = sd
            outliers.append(low_data)

    if outliers:
        return pd.concat(outliers, ignore_index=True)
    return pd.DataFrame()

def print_stats_table(df, title):
    """Print stats table to console using tabulate"""
    print(f"\n{'='*80}")
    print(f"{title}")
    print('='*80)
    print(tabulate(df, headers='keys', tablefmt='grid', showindex=False, floatfmt='.4f'))
    print()

def save_violin_per_channel(df, metric, outdir, limits=None):
    # Sort by Chan_Sort for proper ordering
    chans = df.sort_values("Chan_Sort")[["Chan_Sort", "Channel"]].drop_duplicates().values
    chan_labels = [ch[1] for ch in chans]  # Use Channel string labels
    chan_sorts = [ch[0] for ch in chans]   # Use Chan_Sort for filtering

    data = [df[df["Chan_Sort"]==c][metric].dropna().values for c in chan_sorts]
    data = [d for d in data if len(d)>0]
    if not data:
        return None

    plt.figure(figsize=(12,4))
    parts = plt.violinplot(data, showmeans=True, showextrema=True, showmedians=False)

    # Add limit line if available
    if limits and limits.get(metric):
        plt.axhline(limits[metric], color='r', linestyle='--', linewidth=1.5, label=f'Limit: {limits[metric]}')
        plt.legend()

    plt.title(f"{metric} distribution per channel")
    plt.xlabel("Channel")
    plt.ylabel(metric)
    # Set x-axis labels to show Channel names
    plt.xticks(range(1, len(chan_labels)+1), chan_labels, rotation=0)
    plt.tight_layout()
    fname = os.path.join(outdir, f"violin_{metric}_per_channel.png")
    plt.savefig(fname, dpi=150)
    plt.close()
    return fname

def save_channel_lane_plot(df, metric, chan_sort, chan_label, outdir, limits=None):
    """Plot metric vs lane for a specific channel"""
    sub = df[df["Chan_Sort"]==chan_sort].sort_values("LaneIdx")
    if sub.empty:
        return None
    y = sub[metric].values
    x = sub["LaneIdx"].values
    mu = np.nanmean(y)
    sd = np.nanstd(y)
    plt.figure(figsize=(8,3))
    plt.scatter(x, y, s=10)
    plt.axhline(mu, linestyle="--", color='blue', alpha=0.7, label=f'Mean: {mu:.4f}')
    plt.axhline(mu+sd, linestyle=":", color='blue', alpha=0.5, label=f'±1σ')
    plt.axhline(mu-sd, linestyle=":", color='blue', alpha=0.5)

    # Add limit line if available
    if limits and limits.get(metric):
        plt.axhline(limits[metric], color='r', linestyle='--', linewidth=1.5, label=f'Limit: {limits[metric]}')

    plt.title(f"Channel {chan_label} {metric} vs LaneIdx (0-79)")
    plt.xlabel("LaneIdx")
    plt.ylabel(metric)
    plt.legend(fontsize=8)
    plt.tight_layout()
    # Use sanitized filename
    fname = os.path.join(outdir, f"chan_{chan_label.replace('-','_')}_{metric}_lanes.png")
    plt.savefig(fname, dpi=150)
    plt.close()
    return fname

def save_dimm_vs_channel_plot(df, metric, outdir, limits=None):
    """Plot DIMM performance across channels (bar chart with error bars)"""
    # Group by DIMM and Channel (using both Chan_Sort for sorting and Channel for display)
    dimm_groups = df.groupby(["DIMM_MFG", "DIMM_PN", "Chan_Sort", "Channel"])[metric].agg(["mean", "min", "max"]).reset_index()
    dimm_groups["DIMM_ID"] = dimm_groups["DIMM_MFG"].str[:10] + "_" + dimm_groups["DIMM_PN"].str[:15]

    unique_dimms = dimm_groups["DIMM_ID"].unique()
    if len(unique_dimms) == 0:
        return None

    fig, axes = plt.subplots(len(unique_dimms), 1, figsize=(12, 2.5*len(unique_dimms)), squeeze=False)

    for idx, dimm_id in enumerate(unique_dimms):
        ax = axes[idx, 0]
        dimm_data = dimm_groups[dimm_groups["DIMM_ID"] == dimm_id].sort_values("Chan_Sort")

        chan_labels = dimm_data["Channel"].values
        means = dimm_data["mean"].values
        mins = dimm_data["min"].values
        maxs = dimm_data["max"].values

        # Calculate error bars (distance from mean to min/max)
        yerr_low = means - mins
        yerr_high = maxs - means

        x_positions = range(len(chan_labels))
        ax.bar(x_positions, means, yerr=[yerr_low, yerr_high], capsize=5, alpha=0.7)

        # Add limit line if available
        if limits and limits.get(metric):
            ax.axhline(limits[metric], color='r', linestyle='--', linewidth=1.5, label=f'Limit: {limits[metric]}')
            ax.legend(fontsize=8)

        ax.set_xlabel("Channel")
        ax.set_ylabel(metric)
        ax.set_title(f"{dimm_id} - {metric} per Channel")
        ax.set_xticks(x_positions)
        ax.set_xticklabels(chan_labels, rotation=45, ha='right')
        ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    fname = os.path.join(outdir, f"dimm_{metric}_vs_channel.png")
    plt.savefig(fname, dpi=150)
    plt.close()
    return fname

def save_dimm_vs_lane_plot(df, metric, outdir, limits=None):
    """Plot DIMM performance across all lanes (flattened view)"""
    dimm_groups = df.groupby(["DIMM_MFG", "DIMM_PN", "LaneIdx"])[metric].agg(["mean", "std"]).reset_index()
    dimm_groups["DIMM_ID"] = dimm_groups["DIMM_MFG"].str[:10] + "_" + dimm_groups["DIMM_PN"].str[:15]

    unique_dimms = dimm_groups["DIMM_ID"].unique()
    if len(unique_dimms) == 0:
        return None

    fig, axes = plt.subplots(len(unique_dimms), 1, figsize=(12, 2.5*len(unique_dimms)), squeeze=False)

    for idx, dimm_id in enumerate(unique_dimms):
        ax = axes[idx, 0]
        dimm_data = dimm_groups[dimm_groups["DIMM_ID"] == dimm_id].sort_values("LaneIdx")

        lanes = dimm_data["LaneIdx"].values
        means = dimm_data["mean"].values
        stds = dimm_data["std"].fillna(0).values

        ax.errorbar(lanes, means, yerr=stds, fmt='o', markersize=3, capsize=2, alpha=0.6)

        # Add limit line if available
        if limits and limits.get(metric):
            ax.axhline(limits[metric], color='r', linestyle='--', linewidth=1.5, label=f'Limit: {limits[metric]}')
            ax.legend(fontsize=8)

        ax.set_xlabel("LaneIdx (0-79)")
        ax.set_ylabel(metric)
        ax.set_title(f"{dimm_id} - {metric} vs Lane")
        ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    fname = os.path.join(outdir, f"dimm_{metric}_vs_lane.png")
    plt.savefig(fname, dpi=150)
    plt.close()
    return fname

def save_test_plot_all_channels(df, metric, outdir, limits=None, mfg_filter=None):
    """Plot all channels on one plot: metric vs lane (0-79)
    Creates one plot per unique DIMM_MFG+DIMM_PN combination.
    Each channel is a separate line with unique color.
    Uses MIN across CS values and datasets (worst case).
    Label format: PCB_Chan-MFG-Last6DigitsPN (MIN, n=X)

    Args:
        df: DataFrame with MBIST data
        metric: Metric to plot
        outdir: Output directory
        limits: Optional limits dict
        mfg_filter: Optional manufacturer filter string (case insensitive)

    Returns:
        List of generated filenames
    """
    # Filter by manufacturer if specified
    if mfg_filter:
        df = df[df["DIMM_MFG"].str.contains(mfg_filter, case=False, na=False)].copy()
        if df.empty:
            print(f"Warning: No data matches MFG filter '{mfg_filter}'")
            return []

    # Get unique MFG+PN combinations
    dimm_combos = df[["DIMM_MFG", "DIMM_PN"]].drop_duplicates()
    if dimm_combos.empty:
        print(f"Warning: No DIMM data found")
        return []

    generated_files = []

    # Create one plot per MFG+PN combination
    for _, dimm_row in dimm_combos.iterrows():
        mfg = dimm_row["DIMM_MFG"]
        pn = dimm_row["DIMM_PN"]

        # Filter to this specific MFG+PN
        df_pn = df[(df["DIMM_MFG"] == mfg) & (df["DIMM_PN"] == pn)].copy()
        if df_pn.empty:
            continue

        fnames = _plot_single_pn(df_pn, metric, outdir, limits, mfg, pn, mfg_filter)
        if fnames:
            generated_files.extend(fnames)

    return generated_files

def _plot_single_pn(df, metric, outdir, limits, mfg, pn, mfg_filter=None):
    """Generate a single plot for one MFG+PN combination"""

    # Define 12 distinct colors
    colors = [
        '#1f77b4',  # blue
        '#ff7f0e',  # orange
        '#2ca02c',  # green
        '#d62728',  # red
        '#9467bd',  # purple
        '#8c564b',  # brown
        '#e377c2',  # pink
        '#7f7f7f',  # gray
        '#bcbd22',  # yellow-green
        '#17becf',  # cyan
        '#ff1493',  # deep pink
        '#00ff00',  # lime
    ]

    # Get unique channels sorted by Chan_Sort
    channels = df.sort_values("Chan_Sort")[["Chan_Sort", "Channel"]].drop_duplicates().values

    plt.figure(figsize=(14, 6))

    max_n = 1  # Track max sample count for generating range plot
    channel_stats = {}  # Store min/max/count for range plot

    for idx, (chan_sort, channel) in enumerate(channels):
        # Get data for this channel
        chan_data = df[df["Chan_Sort"] == chan_sort].copy()

        # Get PCB channel from the channel name (after the dash)
        pcb_chan = channel.split("-")[1] if "-" in channel else channel

        # Group by LaneIdx and aggregate: min, max, count
        lane_agg = chan_data.groupby("LaneIdx")[metric].agg(['min', 'max', 'count']).reset_index()
        lane_agg = lane_agg.sort_values("LaneIdx")

        # Get sample count (should be same across lanes, but take max to be safe)
        n_samples = int(lane_agg['count'].max())
        max_n = max(max_n, n_samples)

        # Store for potential range plot
        channel_stats[pcb_chan] = {
            'lane_agg': lane_agg,
            'chan_sort': chan_sort,
            'n': n_samples,
            'color': colors[idx % len(colors)]
        }

        # Create label with sample count if n > 1
        mfg_short = mfg[:5] if pd.notna(mfg) else "?"
        pn_last6 = pn[-6:] if pd.notna(pn) and len(pn) >= 6 else "?"
        if n_samples > 1:
            label = f"{pcb_chan}-{mfg_short}-{pn_last6} (MIN, n={n_samples})"
        else:
            label = f"{pcb_chan}-{mfg_short}-{pn_last6} (MIN)"

        # Plot MIN line
        color = colors[idx % len(colors)]
        plt.plot(lane_agg["LaneIdx"], lane_agg["min"],
                linewidth=1.0, color=color, label=label, alpha=0.8)

    # Add limit line if available
    if limits and limits.get(metric):
        plt.axhline(limits[metric], color='red', linestyle='--',
                   linewidth=2, label=f'Limit: {limits[metric]}', zorder=1000)

    plt.xlabel("Lane (0-79)")
    plt.ylabel(metric)

    # Generate filename with PN info
    mfg_clean = mfg.replace(" ", "").replace("/", "_")[:10] if pd.notna(mfg) else "unknown"
    pn_clean = pn.replace(" ", "").replace("/", "_")[-10:] if pd.notna(pn) else "unknown"
    base_name = f"{metric}_{mfg_clean}_{pn_clean}"

    fname = os.path.join(outdir, f"{base_name}_all_channels.png")

    # Title with PN info
    title = f"{mfg} {pn}: {metric} vs Lane (MIN across CS)"
    plt.title(title, fontsize=11)
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=9)
    plt.grid(axis='both', alpha=0.3)
    plt.xlim(-2, 81)
    plt.tight_layout()

    plt.savefig(fname, dpi=150, bbox_inches='tight')
    plt.close()

    # Generate range plot if n > 1 for any channel
    if max_n > 1:
        range_fname = _plot_range(channel_stats, metric, outdir, limits, mfg, pn, base_name)
        return [fname, range_fname]

    return [fname]

def _plot_range(channel_stats, metric, outdir, limits, mfg, pn, base_name):
    """Generate min/max range plot when n > 1"""

    plt.figure(figsize=(14, 6))

    for pcb_chan, stats in channel_stats.items():
        lane_agg = stats['lane_agg']
        color = stats['color']
        n = stats['n']

        if n > 1:
            # Calculate range (max - min)
            lane_range = lane_agg.copy()
            lane_range['range'] = lane_range['max'] - lane_range['min']

            # Plot range
            label = f"{pcb_chan} (n={n})"
            plt.plot(lane_range["LaneIdx"], lane_range["range"],
                    linewidth=1.0, color=color, label=label, alpha=0.8)

    plt.xlabel("Lane (0-79)")
    plt.ylabel(f"{metric} Range (MAX - MIN)")
    title = f"{mfg} {pn}: {metric} Variability (MAX-MIN)"
    plt.title(title, fontsize=11)
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=9)
    plt.grid(axis='both', alpha=0.3)
    plt.xlim(-2, 81)
    plt.ylim(bottom=0)  # Range is always positive
    plt.tight_layout()

    fname = os.path.join(outdir, f"{base_name}_range.png")
    plt.savefig(fname, dpi=150, bbox_inches='tight')
    plt.close()

    return fname

def main():
    ap = argparse.ArgumentParser(description="Analyze DDR5 MBIST CSVs")
    ap.add_argument("inputs", nargs="+", help="CSV files or globs")
    ap.add_argument("--outdir", default="mbist_out", help="Output directory")
    ap.add_argument("--plots-per-channel", action="store_true", help="Emit per-channel lane plots")
    ap.add_argument("--limit-channels", type=int, default=None, help="Limit plots to first N channels")
    ap.add_argument("--limits-file", default="dmar.toml", help="TOML file with eye margin limits")
    ap.add_argument("--no-console-tables", action="store_true", help="Disable console table output")
    ap.add_argument("--dimm-plots", action="store_true", help="Generate DIMM perspective plots")
    ap.add_argument("--outlier-threshold", type=float, default=2.0, help="Std dev threshold for low spot detection")
    ap.add_argument("--test-plots", action="store_true", help="Generate test plots only (all channels on one plot)")
    ap.add_argument("--mfg-only", type=str, default=None, help="Filter data by manufacturer (case insensitive glob match)")
    args = ap.parse_args()

    # Load data
    df = stack_inputs(args.inputs)
    os.makedirs(args.outdir, exist_ok=True)

    # Load limits (uses defaults if TOML file not found)
    limits = load_limits(args.limits_file)
    if os.path.exists(args.limits_file):
        print(f"Loaded limits from {args.limits_file}:")
    else:
        print(f"Using default limits (no {args.limits_file} found):")
    for metric, limit in limits.items():
        print(f"  {metric}: {limit}")

    # If test-plots mode, only generate test plots and exit
    if args.test_plots:
        if args.mfg_only:
            print(f"Generating test plots for MFG filter: '{args.mfg_only}'...")
        else:
            print("Generating test plots only...")
        metrics = ["ReadWidth_UI","ReadHeight_V","WriteWidth_UI","WriteHeight_V"]
        all_files = []
        for metric in metrics:
            fnames = save_test_plot_all_channels(df, metric, args.outdir, limits=limits, mfg_filter=args.mfg_only)
            if fnames:
                for fname in fnames:
                    print(f"  Generated: {fname}")
                all_files.extend(fnames)
        print(f"\nTest plots complete! Generated {len(all_files)} plot(s) in: {args.outdir}")
        return

    # Calculate statistics
    by_ccs = stats_by(df, ["Channel", "Chan_Sort", "CS", "SC"])
    by_chan = stats_by(df, ["Channel", "Chan_Sort"])
    by_dimm = stats_by(df, ["DIMM_MFG","DIMM_PN"]).sort_values(["DIMM_MFG","DIMM_PN"])

    # Save CSV tables
    by_ccs.to_csv(os.path.join(args.outdir, "stats_by_chan_cs_sc.csv"), index=False)
    by_chan.to_csv(os.path.join(args.outdir, "stats_by_channel.csv"), index=False)
    by_dimm.to_csv(os.path.join(args.outdir, "stats_by_dimm.csv"), index=False)

    # Print console tables
    if not args.no_console_tables:
        print_stats_table(by_chan, "Statistics by Channel")
        print_stats_table(by_dimm, "Statistics by DIMM")

    # Identify low spots
    outliers = identify_low_spots(df, limits=limits, threshold_factor=args.outlier_threshold)
    if not outliers.empty:
        outliers.to_csv(os.path.join(args.outdir, "low_spots.csv"), index=False)
        if not args.no_console_tables:
            print_stats_table(outliers, "LOW SPOTS DETECTED")
        print(f"  Found {len(outliers)} low spot measurements")
    else:
        print("  No low spots detected")

    # Generate plots
    metrics = ["ReadWidth_UI","ReadHeight_V","WriteWidth_UI","WriteHeight_V"]

    # Violin plots per channel
    for metric in metrics:
        save_violin_per_channel(df, metric, args.outdir, limits=limits)

    # Per-channel lane plots
    if args.plots_per_channel:
        # Get list of channels with both sort key and label
        chans = df.sort_values("Chan_Sort")[["Chan_Sort", "Channel"]].drop_duplicates().values
        if args.limit_channels is not None:
            chans = chans[:args.limit_channels]
        for metric in metrics:
            for chan_sort, chan_label in chans:
                save_channel_lane_plot(df, metric, chan_sort, chan_label, args.outdir, limits=limits)

    # DIMM perspective plots
    if args.dimm_plots:
        print("Generating DIMM perspective plots...")
        for metric in metrics:
            save_dimm_vs_channel_plot(df, metric, args.outdir, limits=limits)
            save_dimm_vs_lane_plot(df, metric, args.outdir, limits=limits)

    print(f"\nAnalysis complete! Output written to: {args.outdir}")
    print(f"  - CSV tables: stats_by_*.csv")
    if not outliers.empty:
        print(f"  - Low spots: low_spots.csv ({len(outliers)} entries)")
    print(f"  - Plots: *.png")

if __name__ == "__main__":
    main()
