# dmar-report

DRAM Margining Report Generator

## Overview

This tool is used to collect all the relevant data generated as part of DRAM
margining on AMD EPYC Turin systems. This includes:
- Populated Channel / DIMM / Ranks
- SPD data
- Per-lane read/write data eye width and height
- BDAT

> **NOTE**: This tool only runs on illumos systems.

## Usage

Building on an illumos system:

```console
$ cargo build
```

The resulting binary (`dmar-report`) can then be run on the target system:

```console
root@teapot:~# ./dmar-report
/tmp/teapot-2025-06-04T16:43:40.tar
```

>**Important**: You must run the tool as root.

## Configuration

The system-under-test must have been flashed with the appropriate firmware
configuration. Specifically, the APCB tokens:
- `APCB_TOKEN_UID_BDAT_SUPPORT = Enabled`
- `APCB_TOKEN_UID_MEM_MBIST_DATAEYE_SILENT_EXECUTION_DDR = Enabled`