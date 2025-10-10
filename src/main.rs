use std::collections::BTreeMap;

use anyhow::Context;

mod bdat;
mod mc;
mod sys;

fn cmd(prog: &str, args: &[&str]) -> anyhow::Result<String> {
    let output = std::process::Command::new(prog)
        .env_clear()
        .args(args)
        .output()
        .with_context(|| format!("Failed to run `{prog} args={args:?}`"))?;
    if !output.status.success() {
        // Try to get any error output
        let mut out = String::new();

        if let Some(code) = output.status.code() {
            out.push_str(&format!("exit code {code}"));
        }

        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let extra = if stderr.is_empty() {
            String::from_utf8_lossy(&output.stdout).trim().to_string()
        } else {
            stderr
        };

        if !extra.is_empty() {
            if !out.is_empty() {
                out.push_str(": ");
            }
            out.push_str(&extra);
        }

        anyhow::bail!("`{prog} args={args:?}` failed: {out}");
    }
    Ok(String::from_utf8(output.stdout)?.trim().to_string())
}

fn main() -> anyhow::Result<()> {
    use std::fs;

    let umc = mc::ZenUmc::open(0).context("Failed to get ZenUmc handle")?;
    let chans = umc.discover()?;

    // 0. Create temp folder to collect results into
    let out_dir = tempfile::tempdir().context("Failed to make tempdir")?;
    let hostname = cmd("/usr/bin/uname", &["-n"]).context("Failed to get hostname")?;
    let out_path = out_dir.path().join(&hostname);
    fs::create_dir(&out_path).context("Failed to create hostname dir")?;

    let have_pilot = fs::exists("/usr/bin/pilot").context("Failed to check for pilot binary")?;

    // 1. Write out the system info via pilot (if present)
    if have_pilot {
        let system_info = cmd("/usr/bin/pilot", &["local", "info", "-j"])
            .context("Failed to grab system info with pilot")?;
        fs::write(out_path.join("system_info.json"), system_info)
            .context("Failed to write system info")?;
    }

    // 2. Write out the BDAT
    let bdat = bdat::find_bdat().context("Failed to get BDAT")?;
    fs::write(out_path.join("BDAT.bin"), &bdat).context("Failed to write BDAT")?;

    // 3. Write out the SPD data
    let spd_dir = out_path.join("SPD");
    fs::create_dir(&spd_dir).context("Failed to create SPD dir")?;
    for chan in &chans {
        let c = chan.chan;
        for dimm in &chan.dimms {
            let d = dimm.dimm;
            if dimm.spd.is_empty() {
                eprintln!("Channel {c} DIMM {d} - No SPD data found!");
                continue;
            }
            fs::write(spd_dir.join(format!("chan_{c}_dimm_{d}.bin")), &dimm.spd).with_context(
                || format!("Failed to write raw SPD data for Channel {c} DIMM {d}"),
            )?;

            if !dimm.spd_json.is_empty() {
                fs::write(
                    spd_dir.join(format!("chan_{c}_dimm_{d}.json")),
                    &dimm.spd_json,
                )
                .with_context(|| {
                    format!("Failed to write JSON SPD data for Channel {c} DIMM {d}")
                })?;
            }
        }
    }

    // 4. Write out DIMM info
    {
        #[derive(serde::Serialize)]
        struct Chan<'a> {
            chan: u8,
            slot: char,
            dimms: BTreeMap<u8, &'a mc::DimmInfo>,
        }

        let dimms = chans
            .iter()
            .map(|c| Chan {
                chan: c.chan,
                slot: c.slot,
                dimms: c.dimms.iter().map(|d| (d.dimm, &d.info)).collect(),
            })
            .collect::<Vec<_>>();

        let mut dimms_json = fs::File::create_new(out_path.join("dimms.json"))
            .context("Failed to create dimms.json")?;
        serde_json::to_writer(&mut dimms_json, &dimms).context("Failed to write out dimms.json")?;
    }

    // 5. Pull out and write the margining data
    {
        #[derive(serde::Serialize)]
        struct Chan<'a> {
            chan: u8,
            slot: char,
            clock: u32,
            speed: u32,
            dimms: BTreeMap<u8, Dimm<'a>>,
        }
        #[derive(serde::Serialize)]
        struct Dimm<'a> {
            ranks: BTreeMap<u8, Rank<'a>>,
        }
        #[derive(serde::Serialize)]
        struct Rank<'a> {
            sub_chans: Vec<SubChannel<'a>>,
        }
        #[derive(serde::Serialize)]
        struct SubChannel<'a> {
            data_eyes: &'a [mc::DataEye],
        }

        #[rustfmt::skip]
        let margins = chans
            .iter()
            .map(|c| Chan {
                chan: c.chan,
                slot: c.slot,
                clock: c.clock,
                speed: c.speed,
                dimms: c.dimms.iter().map(|d| (d.dimm, Dimm {
                    ranks: d.ranks.iter().map(|r| (r.rank, Rank {
                        sub_chans: r.sub_chans.iter().map(|s| SubChannel {
                            data_eyes: &s.data_eyes
                        }).collect()
                    })).collect()
                })).collect(),
            }).collect::<Vec<_>>();

        let mut margins_json = fs::File::create_new(out_path.join("margins.json"))
            .context("Failed to create margins.json")?;
        serde_json::to_writer(&mut margins_json, &margins)
            .context("Failed to write out margins.json")?;
    }

    // 6. Also write out the full set of umc data (including PHY data) and decoder snapshot
    {
        let mut raw_json =
            fs::File::create_new(out_path.join("raw.json")).context("Failed to create raw.json")?;
        serde_json::to_writer(&mut raw_json, &chans).context("Failed to write raw umc data")?;

        fs::write(
            out_path.join("mc_decode_snapshot.json"),
            umc.decode_snapshot()?,
        )
        .context("Failed to write decode snapshot")?;
    }

    // Finally `tar` everything up
    let datetime = cmd("/usr/bin/date", &["+%Y-%m-%dT-%H-%M-%S"])?;
    let archive = format!("/tmp/{hostname}-{datetime}.tar");
    let out_dir = out_dir.path().to_str().expect("non-unicode tmp path??");
    cmd("tar", &["-cf", &archive, "-C", out_dir, &hostname]).context("Failed to tar results")?;
    println!("{archive}");

    Ok(())
}
