# Test Plots - All Channels Overview

## Overview
New `--test-plots` flag generates 4 comprehensive plots showing all 12 channels on a single plot for easy comparison.

---

## Plot Details

### Format
- **X-axis:** Lane (0-79)
- **Y-axis:** Metric value (UI or V)
- **12 colored lines:** One per channel
- **Line style:** Thin (1.0 width), 80% opacity
- **Legend:** PCB_Chan-MFG-Last6DigitsPN (MIN)
- **Data aggregation:** MIN across CS values (worst case)

### Metrics (4 plots)
1. `test_ReadWidth_UI_all_channels.png`
2. `test_ReadHeight_V_all_channels.png`
3. `test_WriteWidth_UI_all_channels.png`
4. `test_WriteHeight_V_all_channels.png`

### Color Palette (12 distinct colors)
```
1.  Blue        (#1f77b4)
2.  Orange      (#ff7f0e)
3.  Green       (#2ca02c)
4.  Red         (#d62728)
5.  Purple      (#9467bd)
6.  Brown       (#8c564b)
7.  Pink        (#e377c2)
8.  Gray        (#7f7f7f)
9.  Yellow-Green(#bcbd22)
10. Cyan        (#17becf)
11. Deep Pink   (#ff1493)
12. Lime        (#00ff00)
```

---

## Label Format

**Pattern:** `PCB_Chan-MFG-Last6DigitsPN (MIN)`

**Examples:**
- `C-Micro-64BF1 (MIN)` → PCB channel C, Micron, PN ends in 64BF1, MIN value
- `I-SK Hy-RC554N (MIN)` → PCB channel I, SK Hynix, PN ends in RC554N, MIN value
- `J-SK Hy-RC548N (MIN)` → PCB channel J, SK Hynix, PN ends in RC548N, MIN value

**MFG abbreviations:**
- "Micron Technology" → "Micro" (first 5 chars)
- "SK Hynix" → "SK Hy" (first 5 chars)

---

## Features

### Limit Lines
- Red dashed line shows pass/fail limit from `dmar.toml`
- Displayed in legend with value

### Grid
- Both X and Y axes have light grid (30% alpha)
- Helps identify specific lane numbers

### Legend
- Positioned outside plot area (upper left)
- All 12 channels labeled
- Limit line included if applicable

### X-axis Range
- Extends slightly beyond 0-79 (-2 to 81)
- Makes edge data points more visible

---

## Usage

### Generate Test Plots Only
```bash
python3 mbist_data_analyze.py BRM*.csv --outdir test_out --test-plots
```

**Output:**
- 4 PNG files in `test_out/`
- No CSV tables generated
- No statistics printed to console
- Fast execution (skips all other analysis)

### With Custom Limits File
```bash
python3 mbist_data_analyze.py BRM*.csv --outdir test_out --test-plots --limits-file custom.toml
```

---

## Data Aggregation

### Multiple CS (Chip Select) Values
If a channel has multiple CS values (0, 1), the data uses **MIN per lane** (worst case):
- Groups by `LaneIdx` (0-79)
- Takes **minimum** of metric across all CS values
- Shows the worst-case performance for each lane
- Results in one line per channel representing worst case

### Example
```
Channel 0-C, CS=0, Lane 0: ReadWidth = 0.50
Channel 0-C, CS=1, Lane 0: ReadWidth = 0.52
→ Plotted value: 0.50 (MIN - worst case)
```

### Rationale
- **Worst case analysis:** MIN shows the weakest performance
- **Pass/fail testing:** System is only as good as its worst CS
- **Conservative approach:** Identifies problem areas more reliably

---

## Interpretation

### Good Patterns
- All 12 lines clustered together
- Smooth profiles without sharp dips
- All lines above limit line

### Problem Indicators
- Lines significantly separated (channel-to-channel variation)
- Sharp dips in specific lanes (board routing issues)
- Lines crossing below limit line (failures)
- Jagged profiles (inconsistent performance)

### Example Insights
From current data:
- **Channel 6-I (SK Hynix 554N):** Shows lower ReadWidth than others
- **Channel 1-J (SK Hynix 548N):** Shows lower ReadHeight in some lanes
- **Most channels:** Cluster together, indicating good board design consistency

---

## File Size
Plots are ~440-560 KB each due to:
- 12 lines × 80 points = ~960 data points per plot
- High quality (150 DPI)
- Vector-quality rendering

---

## Next Steps

After reviewing test plots:
1. Identify problematic channels
2. Zoom into specific channels with `--plots-per-channel`
3. Generate full analysis with `--dimm-plots` for detailed comparison
4. Export CSV tables for numerical analysis

---

## Technical Notes

### PCB Channel Extraction
- Extracts from combined channel name (e.g., "0-C" → "C")
- Falls back to full channel name if no dash present

### MFG/PN Handling
- Takes first DIMM occurrence for each channel
- Handles missing/NaN values gracefully
- Truncates MFG to 5 chars, takes last 6 chars of PN

### Performance
- Uses pandas groupby for efficient aggregation
- Single-pass data processing
- Legend positioned outside to avoid overlapping data
