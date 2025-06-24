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
/tmp/teapot-2025-06-04T-16-43-40.tar
```

>**Important**: You must run the tool as root.

## Configuration

The system-under-test must have been flashed with the appropriate firmware
configuration. Specifically, the APCB tokens:
- `APCB_TOKEN_UID_BDAT_SUPPORT = Enabled`
- `APCB_TOKEN_UID_MEM_MBIST_DATAEYE_SILENT_EXECUTION_DDR = Enabled`


## Automated Collection

Also provided in the repo is a python script `dmar-runner.py` to automate DRAM
margining in a lab setup:

```
$ IMAGE_DIR=/staff/luqman/bringup/dram-margining/cosmo-mbist/
$ dmar-runner.py $IMAGE_DIR turin-cosmo-1.0.0.5-mbist.efs.json5 cosmo-os
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