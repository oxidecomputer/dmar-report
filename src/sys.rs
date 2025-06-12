#![allow(dead_code, non_camel_case_types)]

use libc::{c_char, c_int};

pub const MC_ZEN_MAX_CHANS: u8 = 12;
pub const MC_ZEN_MAX_SUBCHANS: u8 = 2;
pub const MC_ZEN_MAX_DIMMS: u8 = 2;
pub const MC_ZEN_MAX_RANKS: u8 = 2;

pub const ZEN_UMC_MAX_BITS: usize = 80;
pub const ZEN_UMC_MAX_NIBS: usize = ZEN_UMC_MAX_BITS / (u8::BITS as usize / 2);
pub const ZEN_UMC_MAX_BYTES: usize = ZEN_UMC_MAX_BITS / u8::BITS as usize;

pub const ZEN_UMC_VREF_DAC_CTLS: usize = u8::BITS as usize + 1;
pub const ZEN_UMC_VREF_DAC_BITS: usize = ZEN_UMC_MAX_BYTES * ZEN_UMC_VREF_DAC_CTLS;

#[cfg(target_os = "linux")]
type Ioctl = libc::Ioctl;
#[cfg(not(target_os = "linux"))]
type Ioctl = i32;

const MC_IOC: Ioctl = 0x4d43 << 16;
pub const MC_IOC_GET_DATA: Ioctl = MC_IOC | 8;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
#[repr(transparent)]
pub struct mc_data_type(pub u8);
impl mc_data_type {
    pub const MDT_SPD: Self = Self(0);
    pub const MDT_MARGINS: Self = Self(1);
    pub const MDT_PHY_DATA: Self = Self(2);
    pub const MDT_DRAM_MODE_REGS: Self = Self(3);

    pub const MDT_MAX: Self = Self::MDT_DRAM_MODE_REGS;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
#[repr(transparent)]
pub struct mc_get_data_error(pub u8);
impl mc_get_data_error {
    pub const MGD_OK: Self = Self(0);
    pub const MGD_NO_DATA: Self = Self(1);
    pub const MGD_INVALID_TYPE: Self = Self(2);
    pub const MGD_INVALID_SIZE: Self = Self(3);
    pub const MGD_INVALID_CHAN: Self = Self(4);
    pub const MGD_INVALID_SUBCHAN: Self = Self(5);
    pub const MGD_INVALID_DIMM: Self = Self(6);
    pub const MGD_INVALID_RANK: Self = Self(7);
    pub const MGD_CHAN_EMPTY: Self = Self(8);
    pub const MGD_DIMM_NOT_PRESENT: Self = Self(9);
    pub const MGD_RANK_NOT_ENABLED: Self = Self(10);

    pub const MGD_MAX: Self = Self::MGD_RANK_NOT_ENABLED;
}

#[derive(Clone, Copy)]
#[repr(C)]
pub union mgd_addr {
    pub addr: *mut u8,
    _addr32: u32,
    _addr64: u64,
}

#[derive(Clone, Copy)]
#[repr(C)]
pub union mgd_size {
    pub size: usize,
    _size32: u32,
    _size64: u64,
}

#[derive(Clone, Copy)]
#[repr(C)]
pub struct mc_get_data {
    pub mgd_type: mc_data_type,
    pub mgd_error: mc_get_data_error,
    pub mgd_chan: u8,
    pub mgd_subchan: u8,
    pub mgd_dimm: u8,
    pub mgd_rank: u8,
    pub _mgd_pad: [u8; 2],
    pub mgd_addr: mgd_addr,
    pub mgd_size: mgd_size,
}

impl mc_get_data {
    pub fn size(&self) -> usize {
        // SAFETY: The mgd_size union is used to ensure the overall struct size
        // remains the same between on both 32-bit and 64-bit platforms. Users
        // are always expected to use the native `usize` (`size_t`) variant.
        // The kernel will also ensure it remains valid across ioctl calls.
        unsafe { self.mgd_size.size }
    }
}

impl Default for mc_get_data {
    fn default() -> Self {
        Self {
            mgd_type: mc_data_type(0xFF),
            mgd_error: mc_get_data_error::MGD_OK,
            mgd_chan: 0xFF,
            mgd_subchan: 0xFF,
            mgd_dimm: 0xFF,
            mgd_rank: 0xFF,
            _mgd_pad: [0, 0],
            mgd_addr: mgd_addr {
                addr: std::ptr::null_mut(),
            },
            mgd_size: mgd_size { size: 0 },
        }
    }
}

#[derive(Clone, Copy, Debug, Default, serde::Serialize)]
#[repr(C)]
pub struct mc_zen_margin_t {
    pub rd_dq_delay: [u8; 2],
    pub wr_dq_delay: [u8; 2],
    pub rd_vref: [u8; 2],
    pub wr_vref: [u8; 2],
}

#[derive(Debug, serde::Serialize)]
#[repr(C)]

pub struct mc_dram_mode_regs_t {
    pub mdmr_nregs: u8,
    pub mdmr_ndies: u8,
    pub mdmr_moderegs: [u8],
}

impl mc_dram_mode_regs_t {
    pub fn from_buf(buf: Box<[u8]>) -> Box<Self> {
        assert!(buf.len() >= 2, "expected at least nregs and ndies");
        let nregs = buf[0];
        let ndies = buf[1];
        let sz = usize::from(nregs) * usize::from(ndies);
        assert_eq!(
            buf.len(),
            2 * std::mem::size_of::<u8>() + sz,
            "invalid mode register buffer"
        );
        // Turn the boxed slice into a raw (thin) pointer
        let buf_ptr = Box::into_raw(buf) as *mut u8;
        // Create a raw (fat) slice with a length of `nregs * ndies`. Note this still
        // points at the beginning of the overall buffer.
        let buf_slice = std::ptr::slice_from_raw_parts_mut(buf_ptr, sz);
        // Cast to `*mut mc_dram_mode_regs_t` which preserves the length metadata of `buf_slice`
        // but now represents the length of the dynamically-sized portion of `mc_dram_mode_regs_t`.
        let ptr = buf_slice as *mut Self;
        // Finally, convert the raw pointer to a Box
        // SAFTEY: `ptr` came from `Box::into_raw` and follows the expected memory layout.
        unsafe { Box::from_raw(ptr) }
    }

    /// Returns a slice representing the value of the requested mode register
    /// for all DRAMs, if present.
    pub fn get_regs(&self, reg: u8) -> &[u8] {
        assert!(
            reg < self.mdmr_nregs,
            "Invalid DRAM Mode Register: {reg} (max {})",
            self.mdmr_nregs
        );
        assert_eq!(
            self.mdmr_moderegs.len(),
            usize::from(self.mdmr_ndies) * usize::from(self.mdmr_nregs)
        );
        self.mdmr_moderegs
            .chunks_exact(self.mdmr_ndies.into())
            .nth(reg.into())
            .unwrap()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
#[repr(transparent)]
pub struct spd_error_t(pub u32);
impl spd_error_t {
    pub const LIBJEDEC_SPD_OK: Self = Self(0);
    pub const LIBJEDEC_SPD_NOMEM: Self = Self(1);
    pub const LIBJEDEC_SPD_TOOSHORT: Self = Self(2);
    pub const LIBJEDEC_SPD_UNSUP_TYPE: Self = Self(3);
    pub const LIBJEDEC_SPD_UNSUP_REV: Self = Self(4);

    pub const LIBJEDEC_SPD_ERR_MAX: Self = Self::LIBJEDEC_SPD_UNSUP_REV;
}

#[link(name = "jedec")]
unsafe extern "C" {
    pub fn libjedec_spd(_: *const u8, _: usize, _: *mut spd_error_t) -> *mut nvlist_t;
}

pub const SPD_KEY_MFG_MOD_MFG_NAME: *const c_char = c"mfg.module-mfg-name".as_ptr();
pub const SPD_KEY_MFG_DRAM_MFG_NAME: *const c_char = c"mfg.dram-mfg-name".as_ptr();
pub const SPD_KEY_MFG_MOD_PN: *const c_char = c"mfg.module-pn".as_ptr();
pub const SPD_KEY_MFG_MOD_SN: *const c_char = c"mfg.module-sn".as_ptr();
pub const SPD_KEY_DRAM_WIDTH: *const c_char = c"dram.width".as_ptr();
pub const SPD_KEY_DATA_WIDTH: *const c_char = c"channel.data-width".as_ptr();
pub const SPD_KEY_ECC_WIDTH: *const c_char = c"channel.ecc-width".as_ptr();

pub const DATA_TYPE_UINT32: c_int = 6;
pub const DATA_TYPE_STRING: c_int = 9;

pub enum nvlist_t {}

#[link(name = "nvpair")]
unsafe extern "C" {
    pub fn nvlist_free(_: *mut nvlist_t);
    pub fn nvlist_lookup_pairs(_: *mut nvlist_t, _: c_int, ...) -> c_int;
    pub fn nvlist_print_json(_: *mut libc::FILE, _: *mut nvlist_t) -> c_int;
}

pub enum kvm_t {}

#[repr(C)]
pub struct nlist {
    pub n_name: *mut libc::c_char,
    pub n_value: libc::c_long,
    pub n_scnum: libc::c_short,
    pub n_type: libc::c_ushort,
    pub n_sclass: libc::c_char,
    pub n_numaux: libc::c_char,
}

impl Default for nlist {
    fn default() -> Self {
        Self {
            n_name: std::ptr::null_mut(),
            n_value: Default::default(),
            n_scnum: Default::default(),
            n_type: Default::default(),
            n_sclass: Default::default(),
            n_numaux: Default::default(),
        }
    }
}

#[link(name = "kvm")]
unsafe extern "C" {
    pub fn kvm_open(
        _: *const libc::c_char,
        _: *const libc::c_char,
        _: *const libc::c_char,
        _: libc::c_int,
        _: *const libc::c_char,
    ) -> *mut kvm_t;
    pub fn kvm_close(_: *mut kvm_t) -> libc::c_int;
    pub fn kvm_nlist(_: *mut kvm_t, _: *mut nlist) -> libc::c_int;
    pub fn kvm_kread(
        _: *mut kvm_t,
        _: libc::uintptr_t,
        _: *mut libc::c_void,
        _: libc::size_t,
    ) -> libc::ssize_t;
}
