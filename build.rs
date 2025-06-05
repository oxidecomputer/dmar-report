use std::path::Path;

fn main() -> std::io::Result<()> {
    if std::env::var("CARGO_CFG_TARGET_OS").unwrap() != "illumos" {
        return Ok(());
    }

    let out_dir = std::env::var("OUT_DIR").unwrap();

    // libjedec is currently 'Uncommitted' with no guaranteed API or ABI
    // stability. Thus, there is no unversioned `libjedec.so` in the system
    // search path. We'd still like to be able to link against it while
    // understanding those stability guarantees (or lack thereof).
    // Unfortunately, the verbatim link modifier doesn't seem to work on illumos
    // so we resort to just creating our own unversioned symlink.

    let system_jedec = "/usr/lib/amd64/libjedec.so.1";
    let target_jedec = format!("{out_dir}/libjedec.so");

    println!("cargo:rustc-link-search={out_dir}");
    println!("cargo::rerun-if-changed={system_jedec}");
    println!("cargo::rerun-if-changed={target_jedec}");

    let system_jedec = Path::new(system_jedec);
    let target_jedec = Path::new(&target_jedec);

    assert!(Path::new(system_jedec).exists(), "libjedec.so.1 missing");

    if target_jedec.exists() {
        if target_jedec.canonicalize()? == system_jedec.canonicalize()? {
            return Ok(());
        } else {
            std::fs::remove_file(target_jedec)?;
        }
    }

    std::os::unix::fs::symlink(system_jedec, target_jedec)?;

    Ok(())
}
