# Windows patcher builds and releases

Build the Rust launcher and CLI for `x86_64-pc-windows-msvc` on Windows. Rust
is pinned to 1.97.1 and Cargo.lock fixes dependency versions:

```powershell
cargo fmt --manifest-path patcher/Cargo.toml --all -- --check
cargo test --manifest-path patcher/Cargo.toml --locked
cargo build --manifest-path patcher/Cargo.toml --locked --release
python scripts/package_windows_patcher.py --binary patcher/target/release/nebula-preservation-patcher.exe --output-dir release-artifacts
```

There is no CI workflow for the patcher; build and test it locally. Generic
builds contain no deployment-specific server, CA or frozen bundle pin. For a
portable launch-enabled release with verified embedded material, see
[Windows launcher](LAUNCHER.md#build-a-portable-release).

To publish, upload the ZIP and its checksum to a GitHub Release by hand. Never
attach a patch bundle or game files.

## What the download contains

`nebula-preservation-patcher-windows-x64.zip` contains:

- The compiled `nebula-preservation-patcher.exe` command-line tool.
- A self-contained `README.md`, `THIRD_PARTY_NOTICES.md`, and `Cargo.lock`.
- `BUILD-INFO.json` with the package version, target and source commit.
- `SHA256SUMS` for the contained files.
- The selected project `LICENSE`, `LICENSE.md` or `LICENSE.txt`, only when one
  actually exists in the source. No project license is invented or inferred.

The separately published `SHA256SUMS` verifies the ZIP itself:

```powershell
Get-FileHash .\nebula-preservation-patcher-windows-x64.zip -Algorithm SHA256
Get-Content .\SHA256SUMS
```

Compare the values before extraction. Checksums detect changed bytes; obtain the
checksum and archive from the intended release, because checksums alone are not
a publisher signature. These builds are unsigned. Windows SmartScreen may show
an unknown-publisher or reputation warning. No signing certificate, signature or
SmartScreen reputation is claimed.

## A reviewed bundle is still required

The EXE alone is not an installable preservation client. You need your supported
Steam installation, a separately reviewed patch bundle, and its independently
published manifest SHA256. A developer `release-input` template is not a bundle.
The workflow never invokes a bundle builder, downloads proprietary inputs,
reconstructs a complete game file, or packages synthetic test bundles.

Start with `nebula-preservation-patcher.exe --help`. Follow
[the patcher instructions](../patcher/README.md) for the supported Steam build,
dry run, server configuration, transactional updates and restore. Keep the game
closed and keep its `.nebula-preservation` receipts and backups. Networking and
shared-host acceptance remain separate from compiling this executable; see
[the current project status](../README.md).

## Local build and packaging

From the repository root, with Rust 1.97.1, the MSVC target and Windows C++ build
tools installed:

```powershell
rustup toolchain install 1.97.1 --profile minimal --component rustfmt --target x86_64-pc-windows-msvc
cargo +1.97.1 fmt --manifest-path patcher/Cargo.toml --all -- --check
cargo +1.97.1 test --manifest-path patcher/Cargo.toml --locked --target x86_64-pc-windows-msvc
cargo +1.97.1 build --manifest-path patcher/Cargo.toml --locked --release --target x86_64-pc-windows-msvc
python -B scripts/package_windows_patcher.py --binary patcher/target/x86_64-pc-windows-msvc/release/nebula-preservation-patcher.exe --output-dir patcher-release-new
```

The output directory must not exist. The packager validates an x64 PE32+ EXE,
reads only explicitly selected documentation/lock/license files, and writes a
deterministic ZIP with fixed entry metadata. It never executes the patcher,
reads a Steam installation, accepts arbitrary extra files, or replaces output.
No original game binaries, bundle helpers, private receipts, credentials or
machine paths are added to the ZIP.

The portable packaging and workflow regression checks are included in source
and run in the shared quality gate. They use temporary files and a nonexecuted
synthetic PE header, with no game, bundle or native patcher execution:

```powershell
python -m pip install -r scripts/requirements-ci.txt
python -B scripts/test_package_windows_patcher.py
```

Workflow references were verified against the official
[checkout](https://github.com/actions/checkout/releases/tag/v7.0.1),
[upload-artifact](https://github.com/actions/upload-artifact/releases/tag/v7.0.2)
and [download-artifact](https://github.com/actions/download-artifact/releases/tag/v8.0.2)
releases. The permission model follows
[GitHub's secure workflow guidance](https://docs.github.com/en/actions/reference/security/secure-use).
