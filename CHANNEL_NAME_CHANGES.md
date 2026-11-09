# Channel Naming Changes

## Overview
Modified `mbist_data_analyze.py` to retain PCB channel names (like A, B, C) and create combined channel identifiers.

---

## Changes Made

### Column Structure

**Previous:**
- `Chan` - Numeric channel (converted letters to numbers)
- `Soc_Chan` - SOC channel number
- `PCB_Chan` - PCB channel number (converted from letters)

**New:**
- `Channel` - Combined string: "SOC-PCB" (e.g., "0-C", "1-A")
- `Chan_Num` - Numeric channel for sorting/grouping (uses PCB if available)
- `Soc_Chan` - SOC channel number (unchanged)
- `PCB_Chan` - PCB channel string (preserves letters like A, B, C)

### Examples

**Input CSV:**
```
Soc_Chan,PCB_Chan,CS,SC,Lane,...
0,C,0,0,0,...
0,C,0,0,1,...
1,D,0,0,0,...
```

**Output Columns:**
```
Channel  Chan_Num  Soc_Chan  PCB_Chan  CS  SC  Lane  ...
0-C      2         0         C         0   0   0     ...
0-C      2         0         C         0   0   1     ...
1-D      3         1         D         0   0   0     ...
```

---

## Benefits

### 1. **Retains Original PCB Channel Names**
- No loss of information from letter-based channel names
- Easy to reference physical PCB labels (A, B, C, etc.)

### 2. **Shows SOC-to-PCB Mapping**
- Combined "Channel" column shows the relationship: "SOC-PCB"
- Useful for debugging routing/scrambling issues

### 3. **Proper Sorting**
- `Chan_Num` enables numeric sorting
- Plots and tables appear in correct order (0-C, 1-D, 2-E, etc.)

### 4. **Backward Compatible with Analysis**
- Statistics grouped by `Chan_Num` work correctly
- PCB_Chan preserved for cross-referencing

---

## Updated Outputs

### CSV Tables
All CSV outputs now include the `Channel` column showing combined names:

**stats_by_channel.csv:**
```
Channel,Chan_Num,ReadWidth_UI_min,ReadWidth_UI_max,...
0-C,2,0.4844,0.5625,...
1-D,3,0.4900,0.5700,...
```

**stats_by_chan_cs_sc.csv:**
```
Channel,Chan_Num,CS,SC,ReadWidth_UI_min,...
0-C,2,0,0,0.4844,...
0-C,2,0,1,0.4844,...
```

**low_spots.csv:**
```
Channel,PCB_Chan,CS,SC,Lane,LaneIdx,Metric,Threshold,...
0-C,C,0,0,24,24,WriteHeight_V,0.2100,...
```

### Plots

**Violin Plots:**
- X-axis labels show combined channel names (0-C, 1-D, etc.)
- Ordered by `Chan_Num` for proper sequence

**Per-Channel Lane Plots:**
- Title: "Channel 0-C ReadWidth_UI vs LaneIdx (0-79)"
- Filename: `chan_0_C_ReadWidth_UI_lanes.png`

**DIMM vs Channel Plots:**
- X-axis shows combined channel names
- Rotated labels for readability

---

## Code Changes Summary

### New Functions
- `to_channel_str()` - Preserves letter channel names (A, B, C)

### Modified Functions
- `load_and_normalize()` - Creates `Channel`, `Chan_Num`, preserves `PCB_Chan` as string
- `stats_by()` - Sorts by `Chan_Num` when present
- `identify_low_spots()` - Includes both `Channel` and `PCB_Chan` in output
- `save_violin_per_channel()` - Uses `Channel` labels on x-axis
- `save_channel_lane_plot()` - Takes `chan_num` and `chan_label` parameters
- `save_dimm_vs_channel_plot()` - Uses `Channel` labels on x-axis
- `main()` - Groups by `["Channel", "Chan_Num"]` for statistics

---

## Testing

To verify the changes work correctly:

```bash
python3 mbist_data_analyze.py BRM*.csv --outdir test_out --dimm-plots
```

Check outputs:
1. CSV files should show "Channel" column with "SOC-PCB" format
2. Plot x-axes should display combined channel names
3. PCB_Chan column should retain letters (A, B, C, etc.)

---

## Migration Notes

If you have existing scripts that parse the output CSVs:
- Old `Chan` column is now `Chan_Num` (numeric)
- New `Channel` column contains the descriptive string (e.g., "0-C")
- `PCB_Chan` is now a string, not a number

**Recommended approach:**
- Use `Channel` for display/reporting
- Use `Chan_Num` for sorting/filtering
- Use `PCB_Chan` for referencing physical board labels
