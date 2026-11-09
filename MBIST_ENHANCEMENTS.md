# MBIST Data Analyzer - Enhancement Summary

## Overview
Enhanced `mbist_data_analyze.py` with new visualizations, automated outlier detection, console output, and limit lines from TOML configuration.

---

## New Features

### 1. **DIMM Perspective Visualizations** ✓
Analyze performance from the DIMM's perspective across different channels and lanes.

**New Plots:**
- `dimm_*_vs_channel.png` - Bar charts showing DIMM performance across channels with min/max error bars
- `dimm_*_vs_lane.png` - Line plots showing DIMM performance across all lanes (0-79) with standard deviation

**Use Cases:**
- Compare different DIMM manufacturers/part numbers
- Identify if issues are DIMM-related vs board-related
- Track DIMM performance when rotated across channels

---

### 2. **Automated Low Spot Identification** ✓
Automatically detect lanes with significantly lower performance.

**Detection Method:**
- Values below `mean - threshold*σ` (default: 2σ)
- Also checks against absolute limits from TOML file
- Takes the more restrictive threshold

**Output:**
- `low_spots.csv` - Detailed CSV with all outlier measurements
- Console table showing: Channel, CS, SC, Lane, Metric, Value, Threshold, Mean, StdDev, DIMM info
- Summary count of total outliers found

**Configurable:**
```bash
--outlier-threshold 2.5  # Adjust sensitivity (default: 2.0)
```

---

### 3. **Enhanced Plot Types** ✓

**Min/Max Error Bars:**
- DIMM vs channel plots show error bars from min to max values
- DIMM vs lane plots show ±1 standard deviation error bars

**Improved Lane Plots:**
- Labeled mean line
- Labeled ±1σ lines
- Better legends

---

### 4. **Console Table Output** ✓
Pretty-printed tables to console using `tabulate` library.

**Tables Printed:**
- Statistics by Channel (min/max/mean/std for all metrics)
- Statistics by DIMM (aggregated across all instances)
- Low Spots Detected (if any outliers found)

**Disable if needed:**
```bash
--no-console-tables
```

---

### 5. **Limit Lines on All Plots** ✓
Red dashed lines showing pass/fail limits from TOML configuration.

**Limits Loaded from `dmar.toml`:**
```toml
eye_height_read_limit  = 0.075   # ReadHeight_V
eye_height_write_limit = 0.100   # WriteHeight_V
eye_width_read_limit   = 0.40    # ReadWidth_UI
eye_width_write_limit  = 0.40    # WriteWidth_UI
```

**Applied to:**
- Violin plots per channel
- Per-channel lane plots
- DIMM vs channel plots
- DIMM vs lane plots

**Custom limits file:**
```bash
--limits-file my_limits.toml
```

---

## Command-Line Options

### New Options:
```bash
--limits-file FILE         # TOML file with limits (default: dmar.toml)
--no-console-tables        # Disable console table output
--dimm-plots               # Generate DIMM perspective plots
--outlier-threshold N      # Std dev threshold for low spots (default: 2.0)
```

### Existing Options:
```bash
inputs                     # CSV files or globs (e.g., BRM*.csv)
--outdir DIR               # Output directory (default: mbist_out)
--plots-per-channel        # Generate per-channel lane plots
--limit-channels N         # Limit plots to first N channels
```

---

## Usage Examples

### Quick Analysis with DIMM Plots:
```bash
python3 mbist_data_analyze.py BRM*.csv --outdir results --dimm-plots
```

### Full Analysis (all features):
```bash
python3 mbist_data_analyze.py BRM*.csv \
    --outdir full_analysis \
    --plots-per-channel \
    --dimm-plots \
    --limit-channels 12
```

### Sensitive Outlier Detection:
```bash
python3 mbist_data_analyze.py BRM*.csv \
    --dimm-plots \
    --outlier-threshold 1.5
```

### Custom Limits File:
```bash
python3 mbist_data_analyze.py BRM*.csv \
    --dimm-plots \
    --limits-file custom_limits.toml
```

---

## Output Files

### CSV Tables:
- `stats_by_chan_cs_sc.csv` - Detailed stats per Channel/CS/SC
- `stats_by_channel.csv` - Summary stats per Channel
- `stats_by_dimm.csv` - Summary stats per DIMM (MFG+PN)
- `low_spots.csv` - Outlier measurements (if any detected)

### Plots:
- `violin_<metric>_per_channel.png` - Distribution across channels (4 files)
- `chan<N>_<metric>_lanes.png` - Per-channel lane plots (optional, 4×N files)
- `dimm_<metric>_vs_channel.png` - DIMM performance by channel (4 files)
- `dimm_<metric>_vs_lane.png` - DIMM performance by lane (4 files)

**Metrics:** ReadWidth_UI, ReadHeight_V, WriteWidth_UI, WriteHeight_V

---

## Installation

### Dependencies:
```bash
pip install -r requirements-mbist.txt
```

Or using system packages (recommended):
```bash
sudo apt install python3-pandas python3-numpy python3-matplotlib python3-toml python3-tabulate
```

### Required packages:
- pandas >= 1.5.0
- numpy >= 1.23.0
- matplotlib >= 3.6.0
- toml >= 0.10.0
- tabulate >= 0.9.0

---

## Analysis Workflow

### Single Dataset Analysis:
1. **Load CSV data** - Parse and normalize column names
2. **Calculate statistics** - Per channel, per CS/SC, per DIMM
3. **Identify outliers** - Flag low spots using statistical + absolute thresholds
4. **Generate plots** - Violin, lane, and DIMM perspective visualizations
5. **Output results** - CSV tables, plots, and console summary

### Multiple Dataset Analysis:
When analyzing multiple CSV files with DIMM rotations:
- Aggregate data across runs
- Track DIMM performance across different channels
- Identify whether issues are board-related or DIMM-related
- Average performance across multiple samples

---

## Interpreting Results

### Low Spots Detection:
- **Board-related:** Same channel/lane across different DIMMs
- **DIMM-related:** Same DIMM showing issues across different channels
- **Random:** Isolated occurrences, possibly measurement noise

### DIMM vs Channel Plots:
- **Flat profile:** Good board design, consistent across channels
- **Dips in specific channels:** Board layout issues
- **Consistently low DIMM:** DIMM quality issue

### DIMM vs Lane Plots:
- **Uniform across lanes:** Good overall performance
- **Dips in specific lanes:** Potential routing or termination issues
- **Subchannel differences:** Check lanes 0-39 vs 40-79

---

## Technical Details

### Channel Mapping:
- Handles both numeric and alpha channel labels (A-L → 0-11)
- Supports Soc_Chan and PCB_Chan mapping
- LaneIdx computed as: `Lane + 40*SC` (0-79 indexing)

### Flexible CSV Parsing:
- Normalizes various column name formats
- Handles missing optional columns (DIMM_SN, Board_SN, margins)
- Requires only first 11 core columns

### Statistical Methods:
- Mean, std dev, min, max, count for all metrics
- Outlier detection: `value < mean - threshold*σ`
- Absolute limit checking from TOML config

---

## Notes

- All limit lines are optional (script works without TOML file)
- Console tables can be disabled for cleaner output
- DIMM plots generated only with `--dimm-plots` flag
- Per-channel plots can be limited with `--limit-channels` for faster testing
- Outlier threshold is adjustable based on data variability

---

## Future Enhancements (Potential)

- [ ] Heatmap visualizations for channel×lane performance
- [ ] Temporal analysis for multiple runs over time
- [ ] Pass/fail percentage summaries
- [ ] HTML report generation
- [ ] Interactive plots (plotly)
- [ ] Automated recommendations based on failure patterns
