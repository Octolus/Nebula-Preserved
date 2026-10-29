#![cfg_attr(windows, windows_subsystem = "windows")]
mod credentials;
mod delta;
mod discovery;
mod embedded;
mod endpoint;
#[cfg(windows)]
mod gui;
mod launcher;
mod manifest;
mod remote;
mod transaction;
mod unityfs;

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    version,
    about = "Verified Nebula Realms preservation launcher and patcher"
)]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}
#[derive(Subcommand)]
enum Command {
    /// Open the Windows launcher. Release pins are compiled into the executable.
    Gui {
        /// Developer native acceptance only; never a release default.
        #[arg(long)]
        allow_provisional: bool,
    },
    /// Opt in to loopback proxying over a verified operator-owned TLS root.
    ConfigureRemote {
        #[arg(long)]
        server: String,
        #[arg(long)]
        ca_file: PathBuf,
        #[arg(long)]
        ca_sha256: String,
    },
    ResetRemoteConfig,
    /// Remove only the provisioner's fixed config and DPAPI token, for interrupted setup/reprovisioning.
    ResetPublicConfig,
    /// Encrypt an administrator-issued account credential with Windows CurrentUser DPAPI.
    ConfigurePublic {
        #[arg(long)]
        server: String,
        #[arg(long)]
        authorization_file: PathBuf,
    },
    Discover,
    Inspect {
        #[arg(long)]
        game: Option<PathBuf>,
    },
    Patch {
        #[arg(long)]
        game: Option<PathBuf>,
        #[arg(long)]
        bundle: PathBuf,
        #[arg(long)]
        manifest_sha256: String,
        #[arg(long)]
        server: String,
        #[arg(long)]
        advertise_ip: String,
        #[arg(long)]
        originals: Option<PathBuf>,
        #[arg(long)]
        allow_provisional: bool,
        #[arg(long)]
        dry_run: bool,
        #[arg(long)]
        remote_transport: bool,
    },
    Restore {
        #[arg(long)]
        game: Option<PathBuf>,
    },
    Recover {
        #[arg(long)]
        game: Option<PathBuf>,
    },
    /// Developer build step: canonicalize a UnityFS bundle, without installing it.
    BundleView {
        #[arg(long)]
        input: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
}
fn main() {
    #[cfg(windows)]
    if std::env::args_os().len() > 1 && std::env::args().nth(1).as_deref() != Some("gui") {
        unsafe {
            windows_sys::Win32::System::Console::AttachConsole(u32::MAX);
        }
    }
    if let Err(e) = run() {
        eprintln!("Error: {e:#}");
        #[cfg(windows)]
        if std::env::args_os().len() == 1 || std::env::args().nth(1).as_deref() == Some("gui") {
            let message: Vec<u16> = format!("{e:#}").encode_utf16().chain(Some(0)).collect();
            let title: Vec<u16> = "Nebula Preservation"
                .encode_utf16()
                .chain(Some(0))
                .collect();
            unsafe {
                windows_sys::Win32::UI::WindowsAndMessaging::MessageBoxW(
                    std::ptr::null_mut(),
                    message.as_ptr(),
                    title.as_ptr(),
                    windows_sys::Win32::UI::WindowsAndMessaging::MB_OK
                        | windows_sys::Win32::UI::WindowsAndMessaging::MB_ICONERROR,
                );
            }
        }
        std::process::exit(1);
    }
}
fn run() -> Result<()> {
    let command = Cli::parse().command.unwrap_or(Command::Gui {
        allow_provisional: false,
    });
    match command {
        Command::Gui { allow_provisional } => launcher::gui(allow_provisional)?,
        Command::ConfigureRemote {
            server,
            ca_file,
            ca_sha256,
        } => remote::configure(&server, &ca_file, &ca_sha256)?,
        Command::ResetRemoteConfig => remote::reset()?,
        Command::ResetPublicConfig => credentials::reset()?,
        Command::ConfigurePublic {
            server,
            authorization_file,
        } => credentials::configure(&server, &authorization_file)?,
        Command::Discover => println!("{}", serde_json::to_string_pretty(&discovery::discover()?)?),
        Command::Inspect { game } => {
            let game = discovery::select(game)?;
            discovery::inspect(&game)?;
        }
        Command::Patch {
            game,
            bundle,
            manifest_sha256,
            server,
            advertise_ip,
            originals,
            allow_provisional,
            dry_run,
            remote_transport,
        } => {
            endpoint::validate(&server, &advertise_ip)?;
            let game = discovery::select(game)?;
            let manifest = manifest::load(&bundle, &manifest_sha256)?;
            if manifest.status != "frozen" && !allow_provisional {
                bail!("Bundle is provisional. Root integration and review must freeze its pins before distribution.");
            }
            transaction::patch(
                &game,
                &bundle,
                &manifest,
                &manifest_sha256,
                &server,
                &advertise_ip,
                originals.as_deref(),
                dry_run,
                remote_transport,
            )?;
        }
        Command::Restore { game } => transaction::restore(&discovery::select(game)?)?,
        Command::Recover { game } => transaction::recover(&discovery::select(game)?)?,
        Command::BundleView { input, output } => {
            if output.exists() {
                bail!("Output already exists");
            }
            let bytes =
                manifest::read_bounded(&input, 256 * 1024 * 1024).context("Read UnityFS input")?;
            let canonical = unityfs::canonicalize(&bytes)?;
            transaction::new_file(&output, &canonical)?;
            println!("{}", manifest::hash(&canonical));
        }
    }
    Ok(())
}
