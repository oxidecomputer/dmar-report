// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

use std::ffi::CString;
use std::os::unix::ffi::OsStrExt;

use crate::sys;

use anyhow::Context;

/// The BDAT is allocated a fixed size with 1MiB per socket.
const BDAT_SIZE: usize = 2 * 1024 * 1024;

/// Byte pattern indicating start of the BDAT region.
const BDAT_SIGNATURE: [u8; 4] = *b"BDAT";

/// The global in `bdat_prd` which holds a kernel virtual address to the BDAT.
const BDAT_PRD_BDAT_SYM: &str = "bdat_prd_amdzen_raw";

/// Attempts to grab the entire BDAT from memory, if available.
pub fn find_bdat() -> anyhow::Result<Vec<u8>> {
    // XXX: We don't have a nice way of getting the raw BDAT data right now
    // and so we just interrogate the `bdat_prd` module live.
    let mut kvm = Kvm::open_live()?;

    // Grabbing a `ZenUmc` handle here ensures the `zen_umc` driver is loaded
    // and as well the `bdat_prd` module we need to grab the BDAT.
    let _umc = crate::mc::ZenUmc::open(0).context("Failed to get ZenUmc handle")?;

    // First, we find the global holding the actual pointer to the BDAT
    let bdat_sym = kvm
        .find_sym(BDAT_PRD_BDAT_SYM)
        .context("Failed to find bdat_prd sym")?;

    // Which we must then "dereference" to get the actual kernel VA to the BDAT
    let bdat_addr = {
        let mut buf = [0u8; std::mem::size_of::<usize>()];
        kvm.kread(bdat_sym, &mut buf)
            .context("Failed to read raw BDAT pointer")?;
        usize::from_ne_bytes(buf)
    };

    // No BDAT was found -- confirm BDAT is enabled in firmware
    if bdat_addr == 0 {
        anyhow::bail!("BDAT not available.");
    }

    // Otherwise we can just go ahead and read in the BDAT!
    let mut bdat = vec![0u8; BDAT_SIZE];
    kvm.kread(bdat_addr, &mut bdat)
        .context("Failed to read BDAT")?;

    let bdat_sig = &bdat[..4];
    if bdat_sig != &BDAT_SIGNATURE[..] {
        anyhow::bail!("Expected BDAT signature but got: {bdat_sig:x?}");
    }

    Ok(bdat)
}

/// Rust-y wrapper for `LIBKVM(3LIB)` (Kernel Virtual Memory) routines.
struct Kvm(*mut sys::kvm_t);

impl Kvm {
    /// Get a handle to the currently running kernel.
    fn open_live() -> anyhow::Result<Self> {
        let err_prefix = std::env::current_exe()
            .map(|path| {
                CString::new(path.file_name().unwrap().as_bytes())
                    .ok()
                    .unwrap()
            })
            .unwrap_or_default();
        let hdl = unsafe {
            sys::kvm_open(
                std::ptr::null(), // namelist = NULL => use running kernel
                c"/dev/allkmem".as_ptr(),
                std::ptr::null(), // swapfile = NULL => use running kernel
                libc::O_RDONLY,
                err_prefix.as_ptr(),
            )
        };
        if hdl.is_null() {
            anyhow::bail!("Failed to get kvm handle for running kernel")
        }
        Ok(Self(hdl))
    }

    /// Find the kernel virtual address for a given symbol.
    fn find_sym(&mut self, sym: &str) -> anyhow::Result<usize> {
        let name = CString::new(sym.as_bytes())
            .with_context(|| format!("Failed to make CStr of {sym}"))?;
        let mut nl = [
            sys::nlist {
                n_name: name.as_ptr().cast_mut(),
                ..Default::default()
            },
            sys::nlist::default(),
        ];
        if unsafe { sys::kvm_nlist(self.0, nl.as_mut_ptr()) } != 0 || nl[0].n_type == 0 {
            anyhow::bail!("Failed to lookup symbol {sym}");
        }
        Ok(nl[0].n_value as usize)
    }

    /// Read from the given kernel virtual address into `buf`.
    fn kread(&mut self, addr: usize, buf: &mut [u8]) -> anyhow::Result<()> {
        let sz = isize::try_from(buf.len())
            .with_context(|| format!("Read buffer size ({}) too large", buf.len()))?;
        let read = unsafe { sys::kvm_kread(self.0, addr, buf.as_mut_ptr().cast(), buf.len()) };
        if read == -1 {
            anyhow::bail!("Failed to read {sz} bytes from {addr:#x}");
        }
        if read != sz {
            anyhow::bail!("Failed to read all bytes from {addr:#x} - {read}/{sz}");
        }
        Ok(())
    }
}

impl Drop for Kvm {
    fn drop(&mut self) {
        if unsafe { sys::kvm_close(self.0) } != 0 {
            eprintln!("Failed to close kvm handle.");
        }
    }
}
