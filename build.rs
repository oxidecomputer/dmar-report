fn main() -> std::io::Result<()> {
    if std::env::var("CARGO_CFG_TARGET_OS").unwrap() != "illumos" {
        return Ok(());
    }

    println!("cargo::rerun-if-changed=/usr/lib/libjedec.so.1");
    std::fs::copy(
        "/usr/lib/libjedec.so.1",
        format!("{}/libjedec.so", std::env::var("OUT_DIR").unwrap()),
    )?;
    Ok(())
}
