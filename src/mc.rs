use std::fs::File;
use std::io::Error;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileTypeExt;
use std::path::PathBuf;

use anyhow::Context;
use serde::Serialize;

use crate::sys;

// XXX: Don't hardcode this here
const TURIN_CHAN_MAP: [char; 12] = ['C', 'E', 'F', 'A', 'B', 'D', 'I', 'K', 'L', 'G', 'H', 'J'];

#[derive(Debug, Serialize)]
pub struct Channel {
    pub chan: u8,
    pub slot: char,
    pub dimms: Vec<Dimm>,
    phy: Option<ChannelPhyData>,
    vrefdac_pair: VrefDacPair,
}

#[derive(Clone, Debug, Serialize)]
pub struct DimmInfo {
    module_mfg: String,
    dram_mfg: String,
    part_number: String,
    serial_number: String,
    dram_width: usize,
    data_width: usize,
    ecc_width: usize,
}

impl Default for DimmInfo {
    fn default() -> Self {
        Self {
            module_mfg: "<Unknown>".into(),
            dram_mfg: "<Unknown>".into(),
            part_number: "<Unknown>".into(),
            serial_number: "<Unknown>".into(),
            dram_width: 4,
            data_width: 32,
            ecc_width: 8,
        }
    }
}

#[derive(Debug, Serialize)]
pub struct Dimm {
    pub dimm: u8,
    #[serde(skip)]
    pub spd: Vec<u8>,
    #[serde(skip)]
    pub spd_json: Vec<u8>,
    pub info: DimmInfo,
    pub ranks: Vec<Rank>,
    phy: Option<DimmPhyData>,
}

#[derive(Debug, Serialize)]
pub struct Rank {
    pub rank: u8,
    pub margin: Option<sys::mc_zen_margin_t>,
    pub sub_chans: Vec<SubChannel>,
    phy: Option<RankPhyData>,
}

#[derive(Debug, Serialize)]
pub struct SubChannel {
    pub sub_chan: u8,
    pub margins: Vec<sys::mc_zen_margin_t>,
    pub data_eyes: Vec<DataEye>,
    mode_regs: Option<Box<sys::mc_dram_mode_regs_t>>,
}

fn all_zeros(arr: &[u8]) -> bool {
    arr.iter().all(|x| *x == 0)
}

#[derive(Clone, Copy, Debug, Serialize)]
pub enum VrefDacPair {
    VrefDac01,
    VrefDac23,
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
pub struct DataEye {
    read: (f64, f64),
    write: (f64, f64),
}

/// The nominal voltage for DDR5 supported on Turin.
const VDDQ: f64 = 1.1;

/// Calculate a DRAM VREF value (in volts) for a given VrefDQ value.
fn calc_dram_vref(vref_dq: u8) -> f64 {
    // The DRAM Vref value in volts is expressed as a ratio of VDDQ between
    // [0.35, 0.975] depending on the VrefDQ value in MR10:
    //      VDDQ * (97.5 - VrefDQ * 0.5) / 100
    // So each step of VrefDQ [0, 0x7D] corresponds to 55mV.
    // See JEDEC DDR5 SDRAM Spec (JESD79-5B v1.20) Table 26.
    assert!(
        vref_dq <= 0x7D,
        "VrefDQ exceeded allowed range [0.35, 0.975]"
    );
    const VREF_BASE: f64 = 0.975 * VDDQ;
    const VREF_STEP: f64 = 0.0055;

    // XXX: The JEDEC based calculation is off by 0.5mV compared to AMD's
    // Memeye tool for some reason.
    const VREF_BIAS: f64 = 0.0005;

    VREF_BASE + VREF_BIAS - f64::from(vref_dq) * VREF_STEP
}

/// Calculate a Host VREF value (in volts) for a given VrefDAC control value.
fn calc_host_vref(vref_dac: u8, eight_bit_dac: bool) -> f64 {
    // VREF is relative to VDDQ but is not a fixed value. We use the given VrefDAC
    // value to find the ratio and thus voltage.

    /// There are multiple VREF generators that support different ranges and can be
    /// selected by setting `UMC::Phy::DqDqsRcvCntrl[ExtVrefRange]`.
    // XXX: We currently assume `UMC::Phy::DqDqsRcvCntrl[ExtVrefRange] = 0`
    const EXT_VREF_RANGE: bool = false;

    let (coff_0, coff_1, coff_2) = if EXT_VREF_RANGE {
        (0.302, 0.0049, 0.0025)
    } else {
        (0.46, 0.00379, 0.00190)
    };

    let vddq_ratio = if eight_bit_dac {
        coff_0 + f64::from(vref_dac >> 1) * coff_1 + f64::from(vref_dac & 1) * coff_2
    } else {
        assert_eq!(vref_dac & !0x7F, 0);
        coff_0 + f64::from(vref_dac) * coff_1
    };

    VDDQ * vddq_ratio
}

#[serde_with::serde_as]
#[derive(Clone, Copy, Debug, Serialize)]
#[repr(C)]
pub struct ChannelPhyData {
    ca_delay: [[u8; u8::BITS as usize]; sys::MC_ZEN_MAX_SUBCHANS as usize],
    #[serde_as(as = "[_; sys::ZEN_UMC_VREF_DAC_BITS]")]
    #[serde(skip_serializing_if = "all_zeros")]
    vref_dac0: [u8; sys::ZEN_UMC_VREF_DAC_BITS],
    #[serde_as(as = "[_; sys::ZEN_UMC_VREF_DAC_BITS]")]
    #[serde(skip_serializing_if = "all_zeros")]
    vref_dac1: [u8; sys::ZEN_UMC_VREF_DAC_BITS],
    #[serde_as(as = "[_; sys::ZEN_UMC_VREF_DAC_BITS]")]
    #[serde(skip_serializing_if = "all_zeros")]
    vref_dac2: [u8; sys::ZEN_UMC_VREF_DAC_BITS],
    #[serde_as(as = "[_; sys::ZEN_UMC_VREF_DAC_BITS]")]
    #[serde(skip_serializing_if = "all_zeros")]
    vref_dac3: [u8; sys::ZEN_UMC_VREF_DAC_BITS],
    #[serde_as(as = "[_; sys::ZEN_UMC_MAX_BITS]")]
    #[serde(skip_serializing_if = "all_zeros")]
    dfe_tap2: [u8; sys::ZEN_UMC_MAX_BITS],
    #[serde_as(as = "[_; sys::ZEN_UMC_MAX_BITS]")]
    #[serde(skip_serializing_if = "all_zeros")]
    dfe_tap3: [u8; sys::ZEN_UMC_MAX_BITS],
    #[serde_as(as = "[_; sys::ZEN_UMC_MAX_BITS]")]
    #[serde(skip_serializing_if = "all_zeros")]
    dfe_tap4: [u8; sys::ZEN_UMC_MAX_BITS],
    max_read_latency: [u8; sys::ZEN_UMC_MAX_BYTES],
}

impl Default for ChannelPhyData {
    fn default() -> Self {
        Self {
            ca_delay: [[0; u8::BITS as usize]; sys::MC_ZEN_MAX_SUBCHANS as usize],
            vref_dac0: [0; sys::ZEN_UMC_VREF_DAC_BITS],
            vref_dac1: [0; sys::ZEN_UMC_VREF_DAC_BITS],
            vref_dac2: [0; sys::ZEN_UMC_VREF_DAC_BITS],
            vref_dac3: [0; sys::ZEN_UMC_VREF_DAC_BITS],
            dfe_tap2: [0; sys::ZEN_UMC_MAX_BITS],
            dfe_tap3: [0; sys::ZEN_UMC_MAX_BITS],
            dfe_tap4: [0; sys::ZEN_UMC_MAX_BITS],
            max_read_latency: Default::default(),
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
#[repr(C)]
pub struct DimmPhyData {
    clk_delay: u8,
}

#[serde_with::serde_as]
#[derive(Clone, Copy, Debug, Serialize)]
#[repr(C)]
pub struct RankPhyData {
    cs_delay: [u8; sys::MC_ZEN_MAX_SUBCHANS as usize],
    #[serde_as(as = "[_; sys::ZEN_UMC_MAX_BITS]")]
    rx_delay: [u8; sys::ZEN_UMC_MAX_BITS],
    rx_en_delay: [u16; sys::ZEN_UMC_MAX_NIBS],
    rx_clk_delay: [u8; sys::ZEN_UMC_MAX_NIBS],
    #[serde_as(as = "[_; sys::ZEN_UMC_MAX_BITS]")]
    tx_dq_delay: [u16; sys::ZEN_UMC_MAX_BITS],
    tx_dqs_delay: [u16; sys::ZEN_UMC_MAX_NIBS],
}

impl Default for RankPhyData {
    fn default() -> Self {
        Self {
            cs_delay: [0; sys::MC_ZEN_MAX_SUBCHANS as usize],
            rx_delay: [0; sys::ZEN_UMC_MAX_BITS],
            rx_en_delay: [0; sys::ZEN_UMC_MAX_NIBS],
            rx_clk_delay: [0; sys::ZEN_UMC_MAX_NIBS],
            tx_dq_delay: [0; sys::ZEN_UMC_MAX_BITS],
            tx_dqs_delay: [0; sys::ZEN_UMC_MAX_NIBS],
        }
    }
}

#[derive(Clone, Copy, Debug, thiserror::Error)]
#[error("requested data not present")]
struct NoData;
#[derive(Clone, Copy, Debug, thiserror::Error)]
#[error("requested channel not populated")]
struct ChanEmpty;
#[derive(Clone, Copy, Debug, thiserror::Error)]
#[error("requested dimm not present")]
struct DimmNotPresent;
#[derive(Clone, Copy, Debug, thiserror::Error)]
#[error("requested rank not enabled")]
struct RankNotEnabled;

#[derive(Clone, Copy, Debug, PartialOrd, PartialEq)]
enum DataScope {
    Chan(u8),
    Dimm(u8, u8),
    Rank(u8, u8, u8),
    SubChannel(u8, u8, u8, u8),
}

impl std::fmt::Display for DataScope {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DataScope::Chan(c) => write!(f, "Channel {c}"),
            DataScope::Dimm(c, d) => write!(f, "Channel {c} DIMM {d}"),
            DataScope::Rank(c, d, r) => write!(f, "Channel {c} DIMM {d} Rank {r}"),
            DataScope::SubChannel(c, d, r, sc) => {
                write!(f, "Channel {c} DIMM {d} Rank {r} SubChannel {sc}")
            }
        }
    }
}

fn parse_spd(spd: &[u8]) -> anyhow::Result<(DimmInfo, Vec<u8>)> {
    let mut err = sys::spd_error_t::LIBJEDEC_SPD_OK;
    let spd_nvl = unsafe { sys::libjedec_spd(spd.as_ptr(), spd.len(), &mut err) };
    match err {
        sys::spd_error_t::LIBJEDEC_SPD_OK => {}
        sys::spd_error_t::LIBJEDEC_SPD_NOMEM => anyhow::bail!("Not enough mem to parse SPD"),
        sys::spd_error_t::LIBJEDEC_SPD_TOOSHORT => anyhow::bail!("SPD data truncated"),
        sys::spd_error_t::LIBJEDEC_SPD_UNSUP_TYPE => anyhow::bail!("Unsupported SPD data type"),
        sys::spd_error_t::LIBJEDEC_SPD_UNSUP_REV => anyhow::bail!("Unsupported SPD revision"),
        sys::spd_error_t(e) => panic!("Unexpected error parsing SPD: {e}"),
    }
    assert_ne!(spd_nvl, std::ptr::null_mut());

    struct NvList(*mut sys::nvlist_t);
    impl Drop for NvList {
        fn drop(&mut self) {
            unsafe {
                sys::nvlist_free(self.0);
            }
        }
    }
    let spd_nvl = NvList(spd_nvl);

    let spd_json = {
        let mut buf_ptr = std::ptr::null_mut();
        let mut buf_sz = 0;
        let buf = unsafe { libc::open_memstream(&raw mut buf_ptr, &raw mut buf_sz) };
        if buf.is_null() {
            return Err(Error::last_os_error()).context("Failed to get memstream to write SPD nvl");
        }
        unsafe {
            sys::nvlist_print_json(buf, spd_nvl.0);
        }
        if unsafe { libc::fclose(buf) } != 0 {
            return Err(Error::last_os_error()).context("Failed to close SPD nvl memstream");
        }
        if buf_ptr.is_null() || buf_sz == 0 {
            anyhow::bail!("Failed to convert SPD");
        }
        let spd = Vec::from(unsafe { std::slice::from_raw_parts(buf_ptr.cast::<u8>(), buf_sz) });
        unsafe {
            libc::free(buf_ptr.cast());
        }
        spd
    };

    let mut mmfg: *const libc::c_char = c"<Unknown>".as_ptr();
    let mut dmfg: *const libc::c_char = c"<Unknown>".as_ptr();
    let mut pn: *const libc::c_char = c"<Unknown>".as_ptr();
    let mut sn: *const libc::c_char = c"<Unknown>".as_ptr();
    let mut dram_width = 0u32;
    let mut data_width = 0u32;
    let mut ecc_width = 0u32;

    let ret = unsafe {
        sys::nvlist_lookup_pairs(
            spd_nvl.0,
            0,
            sys::SPD_KEY_MFG_MOD_MFG_NAME,
            sys::DATA_TYPE_STRING,
            &raw mut mmfg,
            sys::SPD_KEY_MFG_DRAM_MFG_NAME,
            sys::DATA_TYPE_STRING,
            &raw mut dmfg,
            sys::SPD_KEY_MFG_MOD_PN,
            sys::DATA_TYPE_STRING,
            &raw mut pn,
            sys::SPD_KEY_MFG_MOD_SN,
            sys::DATA_TYPE_STRING,
            &raw mut sn,
            sys::SPD_KEY_DRAM_WIDTH,
            sys::DATA_TYPE_UINT32,
            &raw mut dram_width,
            sys::SPD_KEY_DATA_WIDTH,
            sys::DATA_TYPE_UINT32,
            &raw mut data_width,
            sys::SPD_KEY_ECC_WIDTH,
            sys::DATA_TYPE_UINT32,
            &raw mut ecc_width,
            std::ptr::null::<libc::c_char>(),
        )
    };
    if ret != 0 {
        anyhow::bail!("Failed to lookup data from SPD: {ret}");
    }

    let convert_str = |s| {
        // SAFETY: The `nvlist_lookup_pairs()` call succeeded meaning our ptrs are valid.
        let cstr = unsafe { std::ffi::CStr::from_ptr(s) };
        // For simplicity we just use `to_string_lossy()` but these should just be ASCII.
        cstr.to_string_lossy().into_owned()
    };

    let module_mfg = convert_str(mmfg);
    let dram_mfg = convert_str(dmfg);
    let part_number = convert_str(pn);
    let serial_number = convert_str(sn);

    let info = DimmInfo {
        module_mfg,
        dram_mfg,
        part_number,
        serial_number,
        dram_width: dram_width as usize,
        data_width: data_width as usize,
        ecc_width: ecc_width as usize,
    };

    Ok((info, spd_json))
}

/// A handle to a `zen_umc` device on the system.
pub struct ZenUmc {
    umc_dev: File,
}

impl ZenUmc {
    const AMDZEN_DEV_PATH: &str = "/devices/pseudo/amdzen@0/";

    pub fn open(soc: u8) -> anyhow::Result<Self> {
        let umc_dev_path = Self::zen_dev_path("zen_umc", &format!("mc-umc-{soc}"))
            .with_context(|| format!("Failed to get zen umc dev path"))?;
        let umc_dev = File::open(&umc_dev_path).with_context(|| {
            format!("Failed to open zen_umc device @ {}", umc_dev_path.display())
        })?;

        Ok(ZenUmc { umc_dev })
    }

    fn raw_get_data(&self, data: &mut sys::mc_get_data) -> std::io::Result<()> {
        assert!(
            data.mgd_type <= sys::mc_data_type::MDT_MAX,
            "invalid type for get data request: {}",
            data.mgd_type.0
        );
        let ret = unsafe {
            libc::ioctl(
                self.umc_dev.as_raw_fd(),
                sys::MC_IOC_GET_DATA,
                data as *mut _,
            )
        };
        if ret == -1 {
            return Err(Error::last_os_error());
        }
        assert!(
            data.mgd_error <= sys::mc_get_data_error::MGD_MAX,
            "unexpected error for get data request {}: {}",
            data.mgd_type.0,
            data.mgd_error.0
        );
        Ok(())
    }

    fn get_data<D: Clone + Default>(
        &self,
        scope: DataScope,
        data_type: sys::mc_data_type,
        descr: &str,
    ) -> anyhow::Result<Vec<D>> {
        let (c, d, r, sc) = match scope {
            DataScope::Chan(c) => (c, 0xFF, 0xFF, 0xFF),
            DataScope::Dimm(c, d) => (c, d, 0xFF, 0xFF),
            DataScope::Rank(c, d, r) => (c, d, r, 0xFF),
            DataScope::SubChannel(c, d, r, sc) => (c, d, r, sc),
        };

        let mut data = sys::mc_get_data {
            mgd_type: data_type,
            mgd_chan: c,
            mgd_dimm: d,
            mgd_rank: r,
            mgd_subchan: sc,
            ..Default::default()
        };

        self.raw_get_data(&mut data)
            .with_context(|| format!("Failed to query for {descr} for {scope}"))?;

        match data.mgd_error {
            // The requested entity exists but not the requested data
            sys::mc_get_data_error::MGD_NO_DATA => anyhow::bail!(NoData),

            // The requested entity and data exist
            sys::mc_get_data_error::MGD_INVALID_SIZE => {
                // Make sure the returned size corresponds to a whole number of `D`.
                assert_eq!(
                    data.size() % std::mem::size_of::<D>(),
                    0,
                    "unexpected {descr} size for {scope} - {}",
                    data.size()
                );
                let count = data.size() / std::mem::size_of::<D>();
                let mut data_arr = vec![D::default(); count];
                data.mgd_addr.addr = data_arr.as_mut_ptr().cast();
                self.raw_get_data(&mut data)
                    .with_context(|| format!("Failed to get {descr} for {scope}"))?;
                assert_eq!(
                    data.mgd_error,
                    sys::mc_get_data_error::MGD_OK,
                    "unexpected error getting {descr} for {scope}"
                );

                return Ok(data_arr);
            }

            sys::mc_get_data_error::MGD_CHAN_EMPTY => anyhow::bail!(ChanEmpty),
            sys::mc_get_data_error::MGD_DIMM_NOT_PRESENT if scope >= DataScope::Dimm(0, 0) => {
                anyhow::bail!(DimmNotPresent)
            }
            sys::mc_get_data_error::MGD_RANK_NOT_ENABLED if scope >= DataScope::Rank(0, 0, 0) => {
                anyhow::bail!(RankNotEnabled)
            }

            // Don't panic for more recent variants
            sys::mc_get_data_error::MGD_INVALID_TYPE
                if data_type == sys::mc_data_type::MDT_PHY_DATA
                    || data_type == sys::mc_data_type::MDT_DRAM_MODE_REGS =>
            {
                anyhow::bail!(NoData)
            }

            sys::mc_get_data_error(e) => {
                panic!("unexpected error querying for {descr} for {scope}: {e}")
            }
        }
    }

    fn get_phy_data<P: Clone + Default>(&self, scope: DataScope) -> anyhow::Result<Vec<P>> {
        assert!(
            !matches!(scope, DataScope::SubChannel(..)),
            "invalid scope for PHY data"
        );
        self.get_data(scope, sys::mc_data_type::MDT_PHY_DATA, "PHY data")
    }

    fn get_spd(&self, c: u8, d: u8) -> anyhow::Result<Vec<u8>> {
        self.get_data(
            DataScope::Dimm(c, d),
            sys::mc_data_type::MDT_SPD,
            "SPD data",
        )
    }

    fn get_rank_margin(&self, c: u8, d: u8, r: u8) -> anyhow::Result<sys::mc_zen_margin_t> {
        let mut margin = self.get_data(
            DataScope::Rank(c, d, r),
            sys::mc_data_type::MDT_MARGINS,
            "per-rank margins",
        )?;
        assert_eq!(
            margin.len(),
            1,
            "expected just a single record for per-rank margins"
        );
        Ok(margin.pop().unwrap())
    }

    fn get_lane_margins(
        &self,
        c: u8,
        d: u8,
        r: u8,
        sc: u8,
    ) -> anyhow::Result<Vec<sys::mc_zen_margin_t>> {
        self.get_data(
            DataScope::SubChannel(c, d, r, sc),
            sys::mc_data_type::MDT_MARGINS,
            "per-lane margins",
        )
    }

    fn get_mode_regs(
        &self,
        c: u8,
        d: u8,
        r: u8,
        sc: u8,
    ) -> anyhow::Result<Box<sys::mc_dram_mode_regs_t>> {
        let reg_buf: Vec<u8> = self.get_data(
            DataScope::SubChannel(c, d, r, sc),
            sys::mc_data_type::MDT_DRAM_MODE_REGS,
            "DRAM Mode Registers",
        )?;
        Ok(sys::mc_dram_mode_regs_t::from_buf(
            reg_buf.into_boxed_slice(),
        ))
    }

    fn read_vrefs(
        &self,
        chan: &Channel,
        dimm: &Dimm,
        sub_chan: usize,
    ) -> anyhow::Result<impl Iterator<Item = (u8, u8, bool)> + Clone> {
        let data_bits = dimm.info.data_width;
        assert!(sub_chan < sys::MC_ZEN_MAX_SUBCHANS as usize);

        let Some(chan_phy) = &chan.phy else {
            anyhow::bail!(NoData);
        };

        // Grab the right VrefDAC pair 0/1 or 2/3
        let vref_dacs = if let VrefDacPair::VrefDac01 = chan.vrefdac_pair {
            (&chan_phy.vref_dac0, &chan_phy.vref_dac1)
        } else {
            (&chan_phy.vref_dac2, &chan_phy.vref_dac3)
        };

        // The VrefDAC values are organized with the data byte values for all subchannels first,
        // followed by the error byte values:
        //      DByte 0 Bit[0-7, DBI] ----+
        //      DByte 1 Bit[0-7, DBI]     |    SubChannel 0 DByte 0-3
        //      DByte 2 Bit[0-7, DBI]     |
        //      DByte 3 Bit[0-7, DBI] ----+
        //      DByte 4 Bit[0-7, DBI] ----+
        //      DByte 5 Bit[0-7, DBI]     |    SubChannel 1 DByte 0-3
        //      DByte 6 Bit[0-7, DBI]     |
        //      DByte 7 Bit[0-7, DBI] ----+
        //      DByte 8 Bit[0-7, DBI] -----    SubChannel 0 DByte 4 (ECC)
        //      DByte 9 Bit[0-7, DBI] -----    SubChannel 1 DByte 4 (ECC)
        //
        // We also don't care for the DBI values and skip those.
        let data_sz = (data_bits / 8) * sys::ZEN_UMC_VREF_DAC_CTLS;
        let errs_off = sys::MC_ZEN_MAX_SUBCHANS as usize * data_sz;

        let vref_dac0 = (
            &vref_dacs.0[sub_chan * data_sz..][..data_sz],
            &vref_dacs.0[errs_off..][sub_chan * sys::ZEN_UMC_VREF_DAC_CTLS..]
                [..sys::ZEN_UMC_VREF_DAC_CTLS - 1],
        );
        // The trained Vref will be the mid-point between the VrefDAC pair.
        // If RxDFE is disabled, we'll have no values treat VrefDAC1 = VrefDAC0 so
        // the mid-point is just VrefDAC0.
        let vref_dac1 = if all_zeros(vref_dacs.1) {
            vref_dac0
        } else {
            (
                &vref_dacs.1[sub_chan * data_sz..][..data_sz],
                &vref_dacs.1[errs_off..][sub_chan * sys::ZEN_UMC_VREF_DAC_CTLS..]
                    [..sys::ZEN_UMC_VREF_DAC_CTLS - 1],
            )
        };

        let vref_dac0_data = vref_dac0
            .0
            .chunks_exact(sys::ZEN_UMC_VREF_DAC_CTLS)
            .map(|c| c.into_iter().copied().take(sys::ZEN_UMC_VREF_DAC_CTLS - 1))
            .flatten();
        let vref_dac1_data = vref_dac1
            .0
            .chunks_exact(sys::ZEN_UMC_VREF_DAC_CTLS)
            .map(|c| c.into_iter().copied().take(sys::ZEN_UMC_VREF_DAC_CTLS - 1))
            .flatten();
        let read_vrefs = vref_dac0_data
            .zip(vref_dac1_data)
            .chain(vref_dac0.1.iter().copied().zip(vref_dac1.1.iter().copied()))
            .map(|(vref_dac0, vref_dac1)| {
                let eight_bit_dac = (vref_dac0 & !0x7F) != 0 || (vref_dac1 & !0x7F) != 0;
                let vref_offset = vref_dac1.abs_diff(vref_dac0) / 2;
                (vref_dac0, vref_offset, eight_bit_dac)
            });

        Ok(read_vrefs)
    }

    /// Converts the raw margin results to a data eye width (in volts) and height (in UI).
    fn margin_to_dataeye(
        &self,
        chan: &Channel,
        dimm: &Dimm,
        rank: &Rank,
        sub_chan: &SubChannel,
    ) -> anyhow::Result<Vec<DataEye>> {
        let (c, d, r, sc) = (chan.chan, dimm.dimm, rank.rank, sub_chan.sub_chan);
        let data_bits = dimm.info.data_width;
        let err_bits = dimm.info.ecc_width;
        assert!(sc < sys::MC_ZEN_MAX_SUBCHANS);
        assert_eq!(
            sub_chan.margins.len(),
            data_bits + err_bits,
            "Number of margin results not equivalent to number of data ({data}) + error ({err}) bits",
            data = data_bits,
            err = err_bits,
        );

        let read_vrefs = self.read_vrefs(chan, dimm, sc.into()).with_context(|| {
            format!(
                "Failed to get trained Rx Vrefs for {}",
                DataScope::SubChannel(c, d, r, sc)
            )
        })?;
        // DRAM Mode Register 10 contains the DRAM side VrefDQ values.
        let Some(write_vrefs) = sub_chan.mode_regs.as_ref().map(|mr| mr.get_regs(10)) else {
            anyhow::bail!(
                "Failed to get trained Tx Vrefs for {}",
                DataScope::SubChannel(c, d, r, sc)
            )
        };

        // The summarized margin results are relative to the min/max trained Vref across ALL lanes.
        fn minmax_vref(vrefs: impl Iterator<Item = u8>) -> (u8, u8) {
            vrefs.fold((u8::MAX, u8::MIN), |(min, max), vref| {
                (vref.min(min), vref.max(max))
            })
        }
        let (read_min, read_max) = minmax_vref(read_vrefs.clone().map(|v| v.0));
        let (write_min, write_max) = minmax_vref(write_vrefs.iter().copied());

        let data_eyes = sub_chan
            .margins
            .iter()
            .zip(read_vrefs)
            .map(|(margin, (_, vref_offset, eight_bit_dac))| {
                let data_eye = |dq_delay: [u8; 2], vref: [u8; 2], min: u8, max: u8, write| {
                    let width = f64::from(dq_delay[0]) + f64::from(dq_delay[1]);
                    let width_ui = width / 64.0;

                    let neg_vref = min.checked_sub(vref[0]).expect("Negative Vref margin");
                    let pos_vref = max.checked_add(vref[1]).expect("Positive Vref margin");
                    let (neg_vref_v, pos_vref_v) = if write {
                        (calc_dram_vref(neg_vref), calc_dram_vref(pos_vref))
                    } else {
                        (
                            calc_host_vref(neg_vref + vref_offset, eight_bit_dac),
                            calc_host_vref(pos_vref + vref_offset, eight_bit_dac),
                        )
                    };
                    let height_v = (pos_vref_v - neg_vref_v).abs();
                    (width_ui, height_v)
                };

                let read = data_eye(
                    margin.rd_dq_delay,
                    margin.rd_vref,
                    read_min,
                    read_max,
                    false,
                );
                let write = data_eye(
                    margin.wr_dq_delay,
                    margin.wr_vref,
                    write_min,
                    write_max,
                    true,
                );

                DataEye { read, write }
            })
            .collect();

        Ok(data_eyes)
    }

    fn fill_ranks(&self, chan: &Channel, dimm: &mut Dimm) -> anyhow::Result<()> {
        let c = chan.chan;
        let d = dimm.dimm;
        'rank_loop: for r in 0..sys::MC_ZEN_MAX_RANKS {
            let mut rank = Rank {
                rank: r,
                margin: None,
                sub_chans: vec![],
                phy: None,
            };

            match self.get_phy_data(DataScope::Rank(c, d, r)) {
                Ok(pdata) => rank.phy = Some(pdata[0]),
                Err(e) if e.is::<NoData>() => {}
                // Chip-Select not enabled for this rank so let's move on
                Err(e) if e.is::<RankNotEnabled>() => continue 'rank_loop,
                Err(err) => anyhow::bail!(err),
            }

            match self.get_rank_margin(c, d, r) {
                Ok(m) => rank.margin = Some(m),
                Err(e) if e.is::<NoData>() => {}
                Err(err) => anyhow::bail!(err),
            }

            for sc in 0..sys::MC_ZEN_MAX_SUBCHANS {
                let mut sub_chan = SubChannel {
                    sub_chan: sc,
                    margins: vec![],
                    data_eyes: vec![],
                    mode_regs: None,
                };

                match self.get_mode_regs(c, d, r, sc) {
                    Ok(mr) => {
                        // The number of DRAMs should match
                        let bit_width = dimm.info.data_width + dimm.info.ecc_width;
                        let ndrams = bit_width / dimm.info.dram_width;
                        if usize::from(mr.mdmr_ndies) != ndrams {
                            anyhow::bail!(
                                "Unexpected number of DRAMs in Mode Register data for {}: {} vs {}",
                                DataScope::SubChannel(c, d, r, sc),
                                mr.mdmr_ndies,
                                ndrams,
                            );
                        }
                        sub_chan.mode_regs = Some(mr);
                    }
                    Err(e) if e.is::<NoData>() => {}
                    Err(err) => anyhow::bail!(err),
                }

                match self.get_lane_margins(c, d, r, sc) {
                    Ok(m) => {
                        sub_chan.margins = m;
                        sub_chan.data_eyes =
                            self.margin_to_dataeye(chan, dimm, &rank, &sub_chan)
                                .context("Failed to convert margin results to data eye")?;
                    }
                    Err(e) if e.is::<NoData>() => {}
                    Err(err) => anyhow::bail!(err),
                }

                rank.sub_chans.push(sub_chan);
            }
            dimm.ranks.push(rank);
        }
        Ok(())
    }

    /// Attempts to discover the DIMMs present on the memory controller,
    /// grabbing the SPD, PHY data and margin data (if present).
    pub fn discover(&self) -> anyhow::Result<Vec<Channel>> {
        let mut chans = vec![];

        'chan_loop: for c in 0..sys::MC_ZEN_MAX_CHANS {
            let mut chan = Channel {
                chan: c,
                slot: TURIN_CHAN_MAP[c as usize], // XXX
                dimms: vec![],
                phy: None,
                vrefdac_pair: VrefDacPair::VrefDac01,
            };

            match self.get_phy_data(DataScope::Chan(c)) {
                Ok(pdata) => {
                    // We only care for the P-state 0 PHY data.
                    let chan_phy: ChannelPhyData = pdata[0];
                    if !all_zeros(&chan_phy.vref_dac2) {
                        chan.vrefdac_pair = VrefDacPair::VrefDac23;
                    }
                    chan.phy = Some(chan_phy);
                }
                Err(e) if e.is::<NoData>() => {}
                // This channel isn't populated, move on
                Err(e) if e.is::<ChanEmpty>() => continue 'chan_loop,
                Err(err) => anyhow::bail!(err),
            }

            'dimm_loop: for d in 0..sys::MC_ZEN_MAX_DIMMS {
                let mut dimm = Dimm {
                    dimm: d,
                    spd: vec![],
                    spd_json: vec![],
                    info: Default::default(),
                    ranks: vec![],
                    phy: None,
                };

                match self.get_phy_data(DataScope::Dimm(c, d)) {
                    Ok(pdata) => dimm.phy = Some(pdata[0]),
                    Err(e) if e.is::<NoData>() => {}
                    // This DIMM isn't present, move on
                    Err(e) if e.is::<DimmNotPresent>() => continue 'dimm_loop,
                    Err(err) => anyhow::bail!(err),
                }

                match self.get_spd(c, d) {
                    Ok(spd) => {
                        dimm.spd = spd;
                        // We'll also try parsing the SPD and pulling out some bits
                        let (dimm_info, spd_json) = parse_spd(&dimm.spd).with_context(|| {
                            format!("Failed to parse SPD data for Channel {c} DIMM {d}")
                        })?;
                        dimm.info = dimm_info;
                        dimm.spd_json = spd_json;
                    }
                    Err(e) if e.is::<NoData>() => {}
                    Err(err) => anyhow::bail!(err),
                }

                // Populate all the ranks for this DIMM
                self.fill_ranks(&chan, &mut dimm)
                    .with_context(|| format!("Failed to get Rank data for Channel {c} DIMM {d}"))?;

                chan.dimms.push(dimm);
            }

            chans.push(chan);
        }

        Ok(chans)
    }

    fn zen_dev_path(dev: &str, node: &str) -> anyhow::Result<PathBuf> {
        let base_dev_path = PathBuf::from(Self::AMDZEN_DEV_PATH);

        let dir = base_dev_path
            .read_dir()
            .context("Failed to read amdzen devices")?;
        for entry in dir {
            let entry = entry.context("Failed to read amdzen dir entry")?;
            let etype = entry.file_type().with_context(|| {
                format!(
                    "Failed to get amdzen dir entry type for {}",
                    entry.file_name().display()
                )
            })?;
            if !entry.file_name().to_string_lossy().starts_with(dev) || !etype.is_dir() {
                continue;
            }

            // Found the base dev path (e.g. /devices/pseudo/amdzen@0/zen_umc@4)
            let mut dev_path = entry.path();

            // Now make sure the requested node (e.g. `mc-umc-0`) exists
            dev_path.as_mut_os_string().push(format!(":{node}"));
            let ftype = std::fs::metadata(&dev_path)
                .with_context(|| format!("Failed to get metadata for {}", dev_path.display()))?
                .file_type();
            anyhow::ensure!(
                ftype.is_char_device(),
                "Expected char device at {}",
                dev_path.display()
            );
            return Ok(dev_path);
        }

        anyhow::bail!("Failed to find matching {dev} device")
    }
}
