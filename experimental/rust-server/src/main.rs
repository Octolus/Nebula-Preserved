use clap::{Parser, Subcommand};
#[derive(Parser)]
#[command(about = "Experimental Rust implementation of the recovered Nebula contracts")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    /// Check loopback HTTP service liveness without opening persistent state.
    Health {
        #[arg(long, default_value = "127.0.0.1:8088")]
        address: std::net::SocketAddr,
    },
    /// Run isolated JSONL differential probe without network listeners.
    Probe,
    /// Serve recovered HTTP contracts; game/world acceptance is still unproven.
    Serve {
        #[arg(long, default_value = "127.0.0.1:8080")]
        bind: std::net::SocketAddr,
        #[arg(long)]
        state_dir: std::path::PathBuf,
        #[arg(long)]
        protocol_dir: std::path::PathBuf,
        #[arg(long)]
        public_access: bool,
        #[arg(long)]
        managed_instances: bool,
        #[arg(long, default_value = "127.0.0.1")]
        advertised_ip: std::net::Ipv4Addr,
        #[arg(long, default_value = "127.0.0.1")]
        world_bind: std::net::Ipv4Addr,
        #[arg(long,default_value_t=8,value_parser=clap::value_parser!(u16).range(1..=32))]
        max_worlds: u16,
        #[arg(long,default_value_t=28000,value_parser=clap::value_parser!(u16).range(1024..=65535))]
        first_scene_port: u16,
        #[arg(long,default_value_t=28031,value_parser=clap::value_parser!(u16).range(1024..=65535))]
        last_scene_port: u16,
        #[arg(long, requires = "admin_operators_file")]
        admin_token_file: Option<std::path::PathBuf>,
        #[arg(long, requires = "admin_token_file")]
        admin_operators_file: Option<std::path::PathBuf>,
        #[arg(long, default_value = "127.0.0.1:8090")]
        admin_bind: std::net::SocketAddr,
    },
}
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    match Cli::parse().command {
        Command::Health { address } => nebula_preserved_server::health::check(address).await,
        Command::Probe => nebula_preserved_server::probe::run(),
        Command::Serve {
            bind,
            state_dir,
            protocol_dir,
            public_access,
            managed_instances,
            advertised_ip,
            world_bind,
            max_worlds,
            first_scene_port,
            last_scene_port,
            admin_token_file,
            admin_operators_file,
            admin_bind,
        } => {
            if !bind.ip().is_loopback() && !public_access {
                anyhow::bail!("Non-loopback HTTP requires --public-access and a TLS reverse proxy");
            }
            if first_scene_port > last_scene_port
                || last_scene_port - first_scene_port >= 32
                || max_worlds > last_scene_port - first_scene_port + 1
            {
                anyhow::bail!("Scene ports must provide a bounded range of 1..32 ports with room for --max-worlds");
            }
            if !protocol_dir.is_dir() {
                anyhow::bail!(
                    "Protocol directory does not exist; use the repository's protocol folder"
                );
            }
            let mut state = nebula_preserved_server::state::State::open(&state_dir, &protocol_dir)?;
            if advertised_ip.is_unspecified()
                || advertised_ip.is_multicast()
                || advertised_ip.is_broadcast()
            {
                anyhow::bail!("Advertised IP must be a unicast IPv4 address");
            }
            state.advertised_ip = advertised_ip.to_string();
            state.managed_instances = managed_instances;
            if managed_instances {
                state.readiness_profile = Some("nonmini-semantic-v1".into());
                nebula_preserved_server::lifecycle::initialize(&state)?;
            }
            if public_access {
                nebula_preserved_server::access::initialize(&state)?;
            }
            let listener = tokio::net::TcpListener::bind(bind).await?;
            let (cancel, receiver) = tokio::sync::watch::channel(false);
            let mut admin =
                if let (Some(token), Some(operators)) = (admin_token_file, admin_operators_file) {
                    if !admin_bind.ip().is_loopback() || admin_bind.port() == bind.port() {
                        anyhow::bail!("Admin API needs a separate loopback port");
                    }
                    let secret = nebula_preserved_server::admin::load_secret_file(&token)?;
                    let operators = nebula_preserved_server::admin::load_operator_file(&operators)?;
                    nebula_preserved_server::admin::initialize(&state, &secret, &operators)?;
                    let admin_listener = tokio::net::TcpListener::bind(admin_bind).await?;
                    tokio::spawn(nebula_preserved_server::admin_http::serve(
                        admin_listener,
                        state.clone(),
                        receiver.clone(),
                    ))
                } else {
                    let mut receiver = receiver.clone();
                    tokio::spawn(async move {
                        if !*receiver.borrow() {
                            let _ = receiver.changed().await;
                        }
                        Ok(())
                    })
                };
            let mut runtime = tokio::spawn(nebula_preserved_server::runtime::run_with_ports(
                state.clone(),
                world_bind,
                max_worlds as usize,
                first_scene_port,
                last_scene_port,
                receiver,
            ));
            eprintln!(
                "Experimental HTTP listener {} (native parity unproven)",
                listener.local_addr()?
            );
            let (result, finished) = tokio::select! {result=nebula_preserved_server::http::serve(listener,state,public_access)=>(result,0),result=&mut runtime=>(result.unwrap_or_else(|e|Err(e.into())),1),result=&mut admin=>(result.unwrap_or_else(|e|Err(e.into())),2)};
            let _ = cancel.send(true);
            if finished != 1 {
                runtime.await??;
            }
            if finished != 2 {
                admin.await??;
            }
            result
        }
    }
}
