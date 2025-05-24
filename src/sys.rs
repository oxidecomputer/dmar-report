#![allow(dead_code, non_camel_case_types)]

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

    pub const MDT_MAX: Self = Self::MDT_PHY_DATA;
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
