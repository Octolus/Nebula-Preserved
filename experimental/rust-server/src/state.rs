use crate::error::{Error, Result};
use rusqlite::Connection;
use std::{
    path::{Path, PathBuf},
    sync::{Arc, Mutex, MutexGuard},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

#[derive(Clone)]
pub struct State {
    pub db: Arc<Mutex<Connection>>,
    pub protocol: Arc<PathBuf>,
    pub state_dir: Arc<PathBuf>,
    pub fixed_time: Option<f64>,
    pub managed_instances: bool,
    pub advertised_ip: String,
    pub readiness_profile: Option<String>,
}
impl State {
    pub fn open(state_dir: &Path, protocol: &Path) -> Result<Self> {
        std::fs::create_dir_all(state_dir)?;
        let conn = Connection::open(state_dir.join("preservation.sqlite3"))?;
        conn.busy_timeout(Duration::from_secs(3))?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "foreign_keys", "ON")?;
        conn.execute_batch(include_str!("schema.sql"))?;
        Ok(Self {
            db: Arc::new(Mutex::new(conn)),
            protocol: Arc::new(protocol.to_path_buf()),
            state_dir: Arc::new(state_dir.to_path_buf()),
            fixed_time: None,
            managed_instances: false,
            advertised_ip: "127.0.0.1".into(),
            readiness_profile: None,
        })
    }
    pub fn connection(&self) -> Result<MutexGuard<'_, Connection>> {
        self.db
            .lock()
            .map_err(|_| Error::new(500, "Database lock unavailable"))
    }
    pub fn now(&self) -> f64 {
        self.fixed_time.unwrap_or_else(|| {
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64()
        })
    }
    pub fn catalog(&self, filename: &str) -> Result<serde_json::Value> {
        if filename.contains(['/', '\\']) || filename.contains("..") {
            return Err(Error::bad("Invalid catalog name"));
        }
        Ok(serde_json::from_slice(&std::fs::read(
            self.protocol.join(filename),
        )?)?)
    }
}
