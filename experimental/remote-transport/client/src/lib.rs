//! Shared profile/TLS policy, testable without a game or proxy listeners.
pub mod profile;
#[cfg(windows)]
mod system_roots;
pub mod tls;
