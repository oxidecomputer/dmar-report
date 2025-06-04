use std::fs::File;
use std::io::Error;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileTypeExt;
use std::path::PathBuf;

use anyhow::Context;
use serde::Serialize;

use crate::sys;

#[derive(Debug, Serialize)]
pub struct Channel {
    pub chan: u8,
    pub dimms: Vec<Dimm>,
    phy: Option<ChannelPhyData>,
}

#[derive(Debug, Serialize)]
pub struct DimmInfo {
    module_mfg: String,
    dram_mfg: String,
    part_number: String,
    serial_number: String,
    dram_width: u32,
}

#[derive(Debug, Serialize)]
pub struct Dimm {
    pub dimm: u8,
    #[serde(skip)]
    pub spd: Vec<u8>,
    #[serde(skip_serializing_if = "Option::is_none")]
    info: Option<DimmInfo>,
    ranks: Vec<Rank>,
    phy: Option<DimmPhyData>,
}

#[derive(Debug, Serialize)]
pub struct Rank {
    rank: u8,
    #[serde(skip_serializing_if = "Option::is_none")]
    margin: Option<Margin>,
    sub_chans: Vec<SubChannel>,
    phy: Option<RankPhyData>,
}

#[derive(Debug, Serialize)]
pub struct SubChannel {
    sub_chan: u8,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    margins: Vec<Margin>,
}

#[derive(Clone, Copy, Debug, Default, Serialize)]
#[repr(C)]
pub struct Margin {
    rd_dq_delay: [u8; 2],
    wr_dq_delay: [u8; 2],
    rd_vref: [u8; 2],
    wr_vref: [u8; 2],
}

fn all_zeros(arr: &[u8]) -> bool {
    arr.iter().all(|x| *x == 0)
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

fn parse_spd(spd: &[u8]) -> anyhow::Result<DimmInfo> {
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

    let mut mmfg: *const libc::c_char = c"<Unknown>".as_ptr();
    let mut dmfg: *const libc::c_char = c"<Unknown>".as_ptr();
    let mut pn: *const libc::c_char = c"<Unknown>".as_ptr();
    let mut sn: *const libc::c_char = c"<Unknown>".as_ptr();
    let mut dram_width = 0u32;

    let ret = unsafe {
        sys::nvlist_lookup_pairs(
            spd_nvl.0,
            0,
            sys::SPD_KEY_MFG_MOD_MFG_NAME,
            sys::DATA_TYPE_STRING,
            &mut mmfg as *mut _,
            sys::SPD_KEY_MFG_DRAM_MFG_NAME,
            sys::DATA_TYPE_STRING,
            &mut dmfg as *mut _,
            sys::SPD_KEY_MFG_MOD_PN,
            sys::DATA_TYPE_STRING,
            &mut pn as *mut _,
            sys::SPD_KEY_MFG_MOD_SN,
            sys::DATA_TYPE_STRING,
            &mut sn as *mut _,
            sys::SPD_KEY_DRAM_WIDTH,
            sys::DATA_TYPE_UINT32,
            &mut dram_width as *mut _,
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

    Ok(DimmInfo {
        module_mfg,
        dram_mfg,
        part_number,
        serial_number,
        dram_width,
    })
}

/// A handle to a `zen_umc` device on the system.
pub struct ZenUmc(File);

impl ZenUmc {
    const AMDZEN_DEV_PATH: &str = "/devices/pseudo/amdzen@0/";

    pub fn open(umc: u8) -> anyhow::Result<Self> {
        let dev_path =
            Self::umc_dev_path(umc).with_context(|| format!("Failed to get zen umc dev path"))?;
        let file = File::open(&dev_path)
            .with_context(|| format!("Failed to open zen_umc device @ {}", dev_path.display()))?;

        Ok(ZenUmc(file))
    }

    fn raw_get_data(&self, data: &mut sys::mc_get_data) -> std::io::Result<()> {
        assert!(
            data.mgd_type <= sys::mc_data_type::MDT_MAX,
            "invalid type for get data request: {}",
            data.mgd_type.0
        );
        let ret = unsafe { libc::ioctl(self.0.as_raw_fd(), sys::MC_IOC_GET_DATA, data as *mut _) };
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
                data.mgd_addr.addr = data_arr.as_mut_ptr() as *mut _;
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

    fn get_rank_margin(&self, c: u8, d: u8, r: u8) -> anyhow::Result<Margin> {
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

    fn get_lane_margins(&self, c: u8, d: u8, r: u8, sc: u8) -> anyhow::Result<Vec<Margin>> {
        self.get_data(
            DataScope::SubChannel(c, d, r, sc),
            sys::mc_data_type::MDT_MARGINS,
            "per-lane margins",
        )
    }

    fn fill_ranks(&self, c: u8, dimm: &mut Dimm) -> anyhow::Result<()> {
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
                };

                match self.get_lane_margins(c, d, r, sc) {
                    Ok(m) => sub_chan.margins = m,
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
                dimms: vec![],
                phy: None,
            };

            match self.get_phy_data(DataScope::Chan(c)) {
                Ok(pdata) => chan.phy = Some(pdata[0]),
                Err(e) if e.is::<NoData>() => {}
                // This channel isn't populated, move on
                Err(e) if e.is::<ChanEmpty>() => continue 'chan_loop,
                Err(err) => anyhow::bail!(err),
            }

            'dimm_loop: for d in 0..sys::MC_ZEN_MAX_DIMMS {
                let mut dimm = Dimm {
                    dimm: d,
                    spd: vec![],
                    info: None,
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
                        let dimm_info = parse_spd(&dimm.spd).with_context(|| {
                            format!("Failed to parse SPD data for Channel {c} DIMM {d}")
                        })?;
                        dimm.info = Some(dimm_info);
                    }
                    Err(e) if e.is::<NoData>() => {}
                    Err(err) => anyhow::bail!(err),
                }

                // Populate all the ranks for this DIMM
                self.fill_ranks(c, &mut dimm)
                    .with_context(|| format!("Failed to get Rank data for Channel {c} DIMM {d}"))?;

                chan.dimms.push(dimm);
            }

            chans.push(chan);
        }

        Ok(chans)
    }

    fn umc_dev_path(umc: u8) -> anyhow::Result<PathBuf> {
        let dev_path = PathBuf::from(Self::AMDZEN_DEV_PATH);

        let dir = dev_path
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
            if !entry.file_name().to_string_lossy().starts_with("zen_umc") || !etype.is_dir() {
                continue;
            }

            // Found the base zen_umc path (e.g. /devices/pseudo/amdzen@0/zen_umc@4)
            let mut zen_umc_path = entry.path();

            // Now make sure the requested `mc-umc-{umc}` node exists
            zen_umc_path
                .as_mut_os_string()
                .push(format!(":mc-umc-{umc}"));
            let ftype = std::fs::metadata(&zen_umc_path)
                .with_context(|| format!("Failed to get metadata for {}", zen_umc_path.display()))?
                .file_type();
            anyhow::ensure!(
                ftype.is_char_device(),
                "Expected char device at {}",
                zen_umc_path.display()
            );
            return Ok(zen_umc_path);
        }

        anyhow::bail!("Failed to find matching memory controller device")
    }
}
