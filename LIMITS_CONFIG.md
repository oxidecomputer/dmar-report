# Eye Margin Limits Configuration

## Default Limits

The eye margin limits are defined at the top of `mbist_data_analyze.py` for easy updates.

### Location in Code

**File:** `mbist_data_analyze.py`
**Lines:** ~11-17

```python
# Default eye margin limits (can be overridden by TOML file if present)
DEFAULT_LIMITS = {
    "ReadHeight_V": 0.075,
    "ReadWidth_UI": 0.40,
    "WriteHeight_V": 0.100,
    "WriteWidth_UI": 0.40,
}
```

---

## Current Values

| Metric | Limit | Unit | Description |
|--------|-------|------|-------------|
| **ReadHeight_V** | 0.075 | Volts | Minimum read eye height |
| **ReadWidth_UI** | 0.40 | UI | Minimum read eye width |
| **WriteHeight_V** | 0.100 | Volts | Minimum write eye height |
| **WriteWidth_UI** | 0.40 | UI | Minimum write eye width |

---

## How Limits Are Used

### Priority Order:
1. **TOML file** (`dmar.toml`) - if present, overrides defaults
2. **DEFAULT_LIMITS** - used if no TOML file found

### Behavior:

#### With TOML file present:
```bash
$ python3 mbist_data_analyze.py BRM*.csv --test-plots --mfg-only Micron

Processing 1 CSV file(s):
  - BRM22250002_micron-new-die-128MB-full-len6-run-20251106-012810.csv

Loaded limits from dmar.toml:
  ReadHeight_V: 0.075
  ReadWidth_UI: 0.4
  WriteHeight_V: 0.1
  WriteWidth_UI: 0.4
```

#### Without TOML file:
```bash
$ python3 mbist_data_analyze.py BRM*.csv --test-plots --mfg-only Micron

Processing 1 CSV file(s):
  - BRM22250002_micron-new-die-128MB-full-len6-run-20251106-012810.csv

Using default limits (no dmar.toml found):
  ReadHeight_V: 0.075
  ReadWidth_UI: 0.4
  WriteHeight_V: 0.1
  WriteWidth_UI: 0.4
```

---

## Updating Limits

### Method 1: Edit Python File (Recommended)

Edit `mbist_data_analyze.py` directly:

```python
DEFAULT_LIMITS = {
    "ReadHeight_V": 0.080,    # Changed from 0.075
    "ReadWidth_UI": 0.45,     # Changed from 0.40
    "WriteHeight_V": 0.110,   # Changed from 0.100
    "WriteWidth_UI": 0.45,    # Changed from 0.40
}
```

**Pros:**
- Single source of truth
- No external file dependency
- Easy version control
- Works everywhere

### Method 2: Override with TOML file

Create or edit `dmar.toml`:

```toml
eye_height_read_limit  = 0.080
eye_width_read_limit   = 0.45
eye_height_write_limit = 0.110
eye_width_write_limit  = 0.45
```

**Pros:**
- Can have different limits per project
- Easy to change without editing code
- Can be passed via `--limits-file` option

**Cons:**
- Must be in same directory as script
- Extra file to manage

---

## Command-Line Override

To use a custom TOML file:

```bash
python3 mbist_data_analyze.py BRM*.csv --test-plots \
    --limits-file /path/to/custom_limits.toml \
    --mfg-only Micron
```

---

## In Plots

Limits appear as **red dashed horizontal lines** with labels:

```
Limit: 0.075
Limit: 0.4
```

Example:
- Values **above the line**: PASS
- Values **below the line**: FAIL (flagged in analysis)

---

## Recommendation

**For stable production limits:**
- Edit `DEFAULT_LIMITS` in the Python file directly
- Commit to version control
- Ensures consistent limits across all runs

**For experimental/temporary limits:**
- Use TOML file with `--limits-file` option
- Keep default limits in code unchanged

---

## Notes

- Limits apply to **MIN values** (worst case across CS and datasets)
- Used in:
  - Plot visualization (red dashed lines)
  - Low spot detection (outlier identification)
  - Pass/fail analysis
- All limits are **minimum thresholds** (values must be ≥ limit)
