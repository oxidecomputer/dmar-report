use anyhow::Context;

mod mc;
mod sys;

fn main() -> anyhow::Result<()> {
    let umc = mc::ZenUmc::open(0).context("Failed to get ZenUmc handle")?;
    let chans = umc.discover()?;

    serde_json::to_writer(std::io::stdout(), &chans)
        .context("Failed to serialize discovered memory channels")?;
    Ok(())
}
