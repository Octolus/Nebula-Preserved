#[derive(Debug, thiserror::Error)]
#[error("{message}")]
pub struct Error {
    pub status: u16,
    pub message: String,
    pub(crate) sqlite_code: Option<rusqlite::ErrorCode>,
}
impl Error {
    pub fn new(status: u16, message: impl Into<String>) -> Self {
        Self {
            status,
            message: message.into(),
            sqlite_code: None,
        }
    }
    pub fn bad(message: impl Into<String>) -> Self {
        Self::new(400, message)
    }
}
impl From<rusqlite::Error> for Error {
    fn from(error: rusqlite::Error) -> Self {
        let mut result = Self::new(500, "Database operation failed");
        if let rusqlite::Error::SqliteFailure(code, _) = error {
            result.sqlite_code = Some(code.code);
        }
        result
    }
}
impl From<serde_json::Error> for Error {
    fn from(_: serde_json::Error) -> Self {
        Self::bad("Invalid JSON")
    }
}
impl From<std::io::Error> for Error {
    fn from(_: std::io::Error) -> Self {
        Self::new(500, "State IO failed")
    }
}
pub type Result<T> = std::result::Result<T, Error>;
