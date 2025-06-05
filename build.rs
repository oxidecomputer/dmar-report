fn main() -> std::io::Result<()> {
    if std::env::var("CARGO_CFG_TARGET_OS").unwrap() != "illumos" {
        return Ok(());
    }

    let out_dir = std::env::var("OUT_DIR").unwrap();
    println!("cargo:rustc-link-search={out_dir}");
    println!("cargo::rerun-if-changed=/usr/lib/amd64/libjedec.so.1");
    println!("cargo::rerun-if-changed={out_dir}/libjedec.so");
    std::fs::copy(
        "/usr/lib/amd64/libjedec.so.1",
        format!("{out_dir}/libjedec.so"),
    )?;
    Ok(())
}
