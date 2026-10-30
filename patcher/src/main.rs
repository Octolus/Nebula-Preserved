#![cfg_attr(windows, windows_subsystem = "windows")]
mod credentials;
mod delta;
mod discovery;
mod embedded;
mod endpoint;
#[cfg(windows)]
mod gui;
mod launcher;
#[cfg(any(windows, test))]
mod launcher_ui;
mod manifest;
mod remote;
#[cfg(windows)]
mod system_roots;
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
    /// Configure verified TLS. Windows certificate trust is the default.
    ConfigureRemote {
        #[arg(long)]
        server: String,
        #[arg(long, requires = "ca_sha256")]
        ca_file: Option<PathBuf>,
        #[arg(long, requires = "ca_file")]
        ca_sha256: Option<String>,
    },
    /// Read-only TLS/backend check; no account, game launch or profile write.
    CheckServer {
        #[arg(long)]
        server: String,
        #[arg(long, requires = "ca_sha256")]
        ca_file: Option<PathBuf>,
        #[arg(long, requires = "ca_file")]
        ca_sha256: Option<String>,
    },
    /// Explicitly upgrade this origin's saved account to Windows TLS trust.
    MigrateSystemTrust {
        #[arg(long)]
        server: String,
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
        } => match (ca_file, ca_sha256) {
            (None, None) => remote::configure_system(&server)?,
            (Some(ca), Some(pin)) => remote::configure(&server, &ca, &pin)?,
            _ => bail!(
                "Supply both CA file and fingerprint, or neither for Windows certificate trust"
            ),
        },
        Command::CheckServer {
            server,
            ca_file,
            ca_sha256,
        } => {
            #[cfg(windows)]
            {
                let server = launcher::origin(&server)?;
                let ca = match (ca_file, ca_sha256) {
                    (None, None) => None,
                    (Some(ca), Some(pin)) => Some(remote::validate_ca_file(&ca, &pin)?),
                    _ => bail!("Supply both CA file and fingerprint, or neither for Windows certificate trust"),
                };
                launcher::preflight(&server, ca.as_deref())?;
                println!("Verified TLS identity and preservation backend response. Account login and gameplay are not tested.");
            }
            #[cfg(not(windows))]
            {
                let _ = (server, ca_file, ca_sha256);
                bail!("Windows certificate trust and player TLS checks require Windows");
            }
        }
        Command::ResetRemoteConfig => remote::reset()?,
        Command::MigrateSystemTrust { server } => remote::migrate_system(&server)?,
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

#[cfg(test)]
mod cli_tests {
    use super::*;
    #[test]
    fn tls_commands_default_to_system_trust_and_require_complete_private_pins() {
        for command in ["configure-remote", "check-server"] {
            assert!(Cli::try_parse_from([
                "patcher",
                command,
                "--server",
                "https://play.example.org:8444"
            ])
            .is_ok());
            assert!(Cli::try_parse_from([
                "patcher",
                command,
                "--server",
                "https://play.example.org:8444",
                "--ca-file",
                "public.der"
            ])
            .is_err());
            assert!(Cli::try_parse_from([
                "patcher",
                command,
                "--server",
                "https://play.example.org:8444",
                "--ca-sha256",
                "00"
            ])
            .is_err());
            assert!(Cli::try_parse_from([
                "patcher",
                command,
                "--server",
                "https://play.example.org:8444",
                "--insecure"
            ])
            .is_err());
        }
    }
}
