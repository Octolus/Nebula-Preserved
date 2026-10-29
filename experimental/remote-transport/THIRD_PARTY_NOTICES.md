# Third-party dependency notice

No third-party source or compiled third-party binary is vendored in this
directory. The Rust dependency graph is declared in `client/Cargo.toml` and
pinned by `client/Cargo.lock`.

Before distributing a build, collect and ship the exact license texts required
by the resolved dependency graph. The direct dependencies commonly use these
license families (verify the exact version and upstream metadata):

- `anyhow`: MIT OR Apache-2.0
- `tokio`: MIT
- `tokio-rustls`: MIT OR Apache-2.0
- `rustls`: Apache-2.0, ISC, and MIT terms depending on the component/version
- `reqwest`: MIT OR Apache-2.0
- `sha2`: MIT OR Apache-2.0
- `url`: MIT OR Apache-2.0
- `zeroize`: Apache-2.0 OR MIT
- `windows-sys`: MIT OR Apache-2.0

Transitive dependencies, including cryptographic components such as `ring`, may
have additional notice requirements. `Cargo.lock` and the upstream crates are
the authority; this summary is not a substitute for a release license audit.
