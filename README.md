# dmar-report

DRAM Margining Report Generator

## Overview

This tool is used to collect all the relevant data generated as part of DRAM
margining on AMD EPYC Turin systems. This includes:
- Populated Channel / DIMM / Ranks
- SPD data
- Per-lane read/write data eye width and height
- BDAT

The suite consists of:
- **`dmar-report`** (Rust): Collection binary that runs on the illumos target system
- **`dmar.py`** (Python): Primary orchestration tool for automated testing and CSV generation
- **`dmar-runner.py`** (Python): Lab automation script (called internally by `dmar.py`)
- **`dmar_tar2csv.py`** (Python): Standalone utility to convert existing results to CSV

> **NOTE**: Only `dmar-report` needs to run on illumos. The Python tools run on the controller host.

## Dependencies

This tool depends on several external repositories that must be built and configured:

- **[amd-host-image-builder](https://github.com/oxidecomputer/amd-host-image-builder)**: Creates boot images with DRAM margining firmware
- **[boot-image-tools](https://github.com/oxidecomputer/boot-image-tools)**: Provides the `bootserver` binary for phase 2 boot
- **AMD firmware blobs**: Required for boot image generation (typically `amd-firmware/BRH/1.0.0.5/`)
- **Helios image directory**: Contains `phbl` and `zfs.img` for booting the target
- **humility**: For target control and flashing (installed via `cargo install humility`)
- **pilot**: For target discovery and communication (part of the Oxide toolchain)

These dependencies can be configured via:
1. `dmar.toml` configuration file (recommended)
2. Environment variables (e.g., `DMAR_BOOTSERVER_PATH`)
3. Command-line arguments to `dmar.py`

See the **Configuration** section below for details.

## Building

On an illumos system:

```console
$ cargo build --release
```

The resulting binary is at `target/release/dmar-report`.

For cross-compilation or development builds, see `cargo build --help`.

## Quick Start

### 1. Build the collection binary

```console
$ cargo build --release
```

### 2. Configure tool paths

Create a `dmar.toml` file with paths to required binaries and directories:

```toml
# Tool paths
bootserver_path = "/path/to/boot-image-tools/target/release/bootserver"
dmar_report_path = "/path/to/dmar-report/target/release/dmar-report"
image_builder_path = "/path/to/amd-host-image-builder/target/release/amd-host-image-builder"

# Image and firmware paths
image_dir = "/path/to/helios-image"
fw_path = "/path/to/amd-firmware/BRH/1.0.0.5"

# Output location
output_root = "."

# Pass/fail criteria
eye_height_read_limit  = 0.075
eye_height_write_limit = 0.100
eye_width_read_limit   = 0.40
eye_width_write_limit  = 0.40
```

### 3. Run a DRAM margining test

```console
$ ./dmar.py boot-config.efs.json5 mb-3 BRM13250005
```

This will:
- Create and flash a boot image with DRAM margining enabled
- Boot the target system
- Collect DRAM margining data
- Generate a CSV with PASS/FAIL results and detailed log

### 4. Review results

```console
$ ls -l BRM13250005-run-*.csv
$ cat dmar.BRM13250005.*.log
```

## Tools

### dmar.py (Primary Tool)

Orchestrates the full DRAM margining workflow:
- Manages configuration via `dmar.toml`, environment variables, and CLI arguments
- Calls `dmar-runner.py` to perform the test
- Captures detailed timing logs
- Converts results tarball to CSV with PASS/FAIL for each lane
- Validates DIMM population against expected configuration

**Usage:**
```console
$ ./dmar.py <BOOT_JSON> <INVENTRON> <BRD_SN>
```

**Arguments:**
- `BOOT_JSON`: Path to EFS boot configuration (`.json5` or `.json`)
- `INVENTRON`: Inventron environment name (e.g., `mb-3`, `mb-0`)
- `BRD_SN`: Board serial number (e.g., `BRM13250005`)

**Common Options:**
- `--profile NAME`: Use settings from `[profiles.NAME]` in `dmar.toml`
- `--outcsv FILE`: Custom output CSV path
- `--print-config`: Display resolved configuration and exit
- `--force`: Overwrite existing CSV
- `-v, --verbose`: Enable detailed logging

For complete options, see `./dmar.py --help`

### dmar-report (Collection Binary)

Runs on the illumos target system to collect DRAM margining data. Produces a tarball containing:
- `system_info.json`: System identification
- `BDAT.bin`: BIOS Data ACPI Table
- `SPD/*.bin` and `SPD/*.json`: Serial Presence Detect data for each DIMM
- `dimms.json`: DIMM information and population
- `margins.json`: Per-lane eye width/height measurements
- `raw.json`: Complete raw data including PHY registers

**Usage:**
```console
root@target:~# ./dmar-report
/tmp/hostname-2025-10-13T-14-23-45.tar
```

> **Important**: Must be run as root on an illumos system.

### dmar-runner.py (Automation Script)

Low-level automation script that handles target preparation, firmware flashing, boot orchestration, and result collection. Called internally by `dmar.py`.

Most users should use `dmar.py` instead. For direct usage, see `./dmar-runner.py --help`

### dmar_tar2csv.py (Post-Processing Tool)

Converts an existing results tarball to CSV using pass/fail limits from a TOML config.

**Usage:**
```console
$ ./dmar_tar2csv.py --in-tar results.tar --out-csv output.csv --toml dmar.toml
```

**Options:**
- `--profile NAME`: Use limits from `[profiles.NAME]` section

For details, see `./dmar_tar2csv.py --help`

## Configuration

### Config File Discovery

`dmar.py` searches for `dmar.toml` in the following order (first found wins):

1. Path specified by `--toml` CLI argument
2. Path in `DMAR_CONFIG` environment variable
3. `./dmar.toml` (current directory)
4. `<script_dir>/dmar.toml` (directory containing `dmar.py`)
5. `<git_root>/dmar.toml` (repository root)
6. `~/.config/dmar/config.toml`
7. `/etc/dmar/config.toml`

### Configuration Priority

Settings are resolved in order (highest to lowest priority):

1. CLI arguments (e.g., `--image-dir /path`)
2. Environment variables (e.g., `DMAR_IMAGE_DIR=/path`)
3. Profile section in TOML: `[profiles.NAME]`
4. Base TOML settings
5. Hardcoded defaults

### Profiles

Profiles allow environment-specific configurations. Use `--profile NAME` or let it default to the `INVENTRON` argument.

**Example:**
```toml
# Base settings
image_dir = "/default/path"
expected_dimms = 12

[profiles.mb-3]
image_dir = "/custom/path/for/mb-3"
expected_dimms = 24

[profiles.mb-0]
expected_dimms = 12
```

```console
$ ./dmar.py boot.json mb-3 BRM13250005
# Uses [profiles.mb-3] settings
```

### Verifying Configuration

```console
$ ./dmar.py boot.json mb-3 BRM13250005 --print-config
```

This displays resolved settings, config file source, active profile, and validates all paths.

### Environment Variables

All settings can be overridden via environment variables:

- `DMAR_IMAGE_DIR`
- `DMAR_FW_PATH`
- `DMAR_BOOTSERVER_PATH`
- `DMAR_DMAR_REPORT_PATH`
- `DMAR_IMAGE_BUILDER_PATH`
- `DMAR_RUNNER_PATH`
- `DMAR_OUTPUT_ROOT`
- `DMAR_EYE_HEIGHT_READ_LIMIT`
- `DMAR_EYE_HEIGHT_WRITE_LIMIT`
- `DMAR_EYE_WIDTH_READ_LIMIT`
- `DMAR_EYE_WIDTH_WRITE_LIMIT`
- `DMAR_EXPECTED_DIMMS`
- `DMAR_EXPECTED_SLOTS` (comma-separated)

## Target System Requirements

The system-under-test must be flashed with firmware that has these APCB tokens enabled:
- `APCB_TOKEN_UID_BDAT_SUPPORT = Enabled`
- `APCB_TOKEN_UID_MEM_MBIST_DATAEYE_SILENT_EXECUTION_DDR = Enabled`

The boot configuration JSON passed to `dmar.py` should specify these settings.

## Output Format

### CSV Structure

The generated CSV contains per-lane measurements with the following columns:

- **Soc_Chan**: SoC memory channel number
- **PCB_Chan**: PCB slot identifier
- **CS**: Chip select (rank)
- **SC**: Sub-channel
- **Lane**: Data lane number
- **Read Width (UI)**: Read eye width in unit intervals
- **Read Height (V)**: Read eye height in volts
- **Write Width (UI)**: Write eye width in unit intervals
- **Write Height (V)**: Write eye height in volts
- **DIMM_MFG**: DIMM manufacturer
- **DIMM_PN**: DIMM part number
- **DIMM_SN**: DIMM serial number
- **Board SN**: Target board serial number
- **margin_read_width**: Margin above threshold (negative = fail)
- **margin_read_height**: Margin above threshold (negative = fail)
- **margin_write_width**: Margin above threshold (negative = fail)
- **margin_write_height**: Margin above threshold (negative = fail)
- **PASS**: `PASS` or `FAIL` based on all four margins

### Log File

The log file (`dmar.<BRD_SN>.<timestamp>.log`) contains:
- Complete console output from the test run
- Timing breakdown (QSPI write, boot times, collection time)
- DIMM summary with population validation
- Cleanup operations

## Examples

### Basic test with default config

```console
$ ./dmar.py turin-cosmo.efs.json5 mb-3 BRM13250005
DRAM Margining ( mb-3-sp )
Preparing target for testing...
Creating boot image...
Writing image to target...
[...]
CSV written to BRM13250005-run-20251013-142345.csv
Log saved to dmar.BRM13250005.20251013.142345.log
```

### Using a specific profile

```console
$ ./dmar.py turin-cosmo.efs.json5 mb-0 BRM13250010 --profile production
```

### Custom output location

```console
$ ./dmar.py turin-cosmo.efs.json5 mb-3 BRM13250005 \
    --output-root /results/dram-margining \
    --outcsv /results/special-test.csv
```

### Override configuration paths

```console
$ ./dmar.py turin-cosmo.efs.json5 mb-3 BRM13250005 \
    --image-dir /custom/helios-build \
    --fw-path /custom/firmware/path
```

### Convert existing results to CSV

```console
$ ./dmar_tar2csv.py \
    --in-tar BRM13250005-2025-10-13T-14-23-45.tar \
    --out-csv reprocessed.csv \
    --toml dmar.toml \
    --profile strict-limits
```

## Advanced Usage

### Direct automation with dmar-runner.py

For advanced users who need direct control over the automation without the CSV conversion and configuration management:

```console
$ IMAGE_DIR=/staff/luqman/bringup/dram-margining/cosmo-mbist/
$ dmar-runner.py $IMAGE_DIR turin-cosmo-1.0.0.5-mbist.efs.json5 cosmo-os \
    --bootserver-path /path/to/bootserver \
    --dmar-report-path /path/to/dmar-report \
    --image-builder-path /path/to/amd-host-image-builder \
    --fw-path /path/to/amd-firmware/BRH/1.0.0.5
DRAM Margining ( cosmo-os )
Preparing target for testing...
Creating boot image...
Writing image to target...
humility: attached to 1fc9:0143:WTECYVHYHSQD4 via CMSIS-DAP
humility: erased 9.75MB in 39 seconds
humility: hashed 32.00MB, wrote 9.75MB in 6 minutes
Starting testing...
MBIST DataEye Test
Booted to x86 (0:04:43.474236 elapsed)
Waiting for phase 2 request...
boot server starting on link isolated0...


received hello! src e8:ea:6a:09:6e:b4 dst ff:ff:ff:ff:ff:ff len 53
msg = "Hello!  I'd like to buy a ramdisk please."
opened image "/staff/luqman/bringup/dram-margining/cosmo-mbist/zfs.img": image (data size 1048576000, image size 1048576000, target size 4294967296, hash b164e3867f7e16386c704eefa01f2c002f27473afa215919c3530df1473ce7e3, dataset rpool/ROOT/ramdisk)
progress: sent up to offset 965344256 (92%)
received finished! src e8:ea:6a:09:6e:b4 dst 02:08:20:1c:2a:da len 46
finished copying!
Waiting for BRM13250010 to boot...
Begin DRAM Margining results collection...
DRAM Margining Test Results: BRM13250010-1986-12-28T-00-00-12.tar

$ tar tvf ./BRM13250010-1986-12-28T-00-00-12.tar
drwxr-xr-x   0/0        0 Dec 28 00:00 1986 BRM13250010/
-rw-r--r--   0/0      311 Dec 28 00:00 1986 BRM13250010/system_info.json
-rw-r--r--   0/0  2097152 Dec 28 00:00 1986 BRM13250010/BDAT.bin
drwxr-xr-x   0/0        0 Dec 28 00:00 1986 BRM13250010/SPD/
-rw-r--r--   0/0     1024 Dec 28 00:00 1986 BRM13250010/SPD/chan_3_dimm_0.bin
-rw-r--r--   0/0     2936 Dec 28 00:00 1986 BRM13250010/SPD/chan_3_dimm_0.json
-rw-r--r--   0/0      211 Dec 28 00:00 1986 BRM13250010/dimms.json
-rw-r--r--   0/0    12020 Dec 28 00:00 1986 BRM13250010/margins.json
-rw-r--r--   0/0    51885 Dec 28 00:00 1986 BRM13250010/raw.json
```

## Troubleshooting

### Configuration issues

```console
$ ./dmar.py boot.json mb-3 BRM13250005 --print-config
```

Check that all paths exist and are accessible.

### Missing dependencies

If you see errors about missing binaries, ensure all dependencies are built and paths are correctly configured in `dmar.toml`.

### Log files

Check the detailed log file for timing information and error messages:

```console
$ cat dmar.<BRD_SN>.<timestamp>.log
```

### Target cleanup

If a test is interrupted, the target may be left in an unexpected state. The cleanup routine attempts to restore:
- Flash device to Flash0
- Boot startup options to 0x0
- UART redirect disabled

Manual cleanup may be required if automatic cleanup fails.
