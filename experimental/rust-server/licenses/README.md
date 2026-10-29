# Rust candidate dependency notices

The repository's original reconstruction code uses the root [MIT
license](../../../LICENSE). These notices retain the separate upstream terms;
they do not relicense dependencies or grant rights to the original game.

[DEPENDENCIES.json](../DEPENDENCIES.json) records each third-party package's
name, version, declared license and repository from locked Cargo metadata.
It includes build/test dependencies and packages for other platforms as well as
runtime dependencies. It is a lock-graph inventory, not a claim that every
listed package is linked into each binary. License expressions are retained as
declared upstream, including older slash-separated expressions.

Each package directory contains its published license and notice texts, copied
without changes except for the explicitly identified SQLite notice excerpt.
No dependency implementation, archive, binary or Cargo cache is included here.
Notices can contain their upstream authors' public attribution details.

Additional notice boundaries:

- `atomic-waker` includes its `LICENSE-THIRD-PARTY`; `matchit` includes both its
  own license and `LICENSE.httprouter`; `unicode-ident` includes `LICENSE-UNICODE`.
  `tracing-core` also retains the nested `src/spin/LICENSE` notice.
- `libsqlite3-sys` retains its MIT license. `SQLITE-NOTICE.txt` contains only the
  copyright disclaimer/blessing at the start of its bundled `sqlite3/sqlite3.h`,
  with the comment closed for this standalone excerpt. The candidate enables
  bundled SQLite, not the optional SQLCipher implementation.
- `r-efi` carries its permission and copyright notice in `AUTHORS`; that file is
  retained unchanged.
- The two `winapi-*-pc-windows-gnu` 0.4.0 packages declare `MIT/Apache-2.0` but
  their registry archives omit license files. Their directories retain the
  shared `LICENSE-MIT` and `LICENSE-APACHE` from locked `winapi` 0.3.9, the same
  upstream project. The inventory preserves each package's own declaration.
- `rust-standard-library-1.90.0/` retains the installed toolchain's MIT and
  Apache texts plus [the standard-library copyright and third-party
  notices](rust-standard-library-1.90.0/COPYRIGHT-library.html). These cover the
  pinned build toolchain's standard library separately from Cargo packages.

The candidate Dockerfile includes this directory and `DEPENDENCIES.json` under
`/usr/share/licenses/nebula-preserved/rust-server/`. Debian runtime packages keep
their own notices in the base image, normally under `/usr/share/doc/`; their
licenses are not replaced by the Rust package inventory. A different toolchain,
feature set, dependency lock or runtime base needs its corresponding review.

Refresh the inventory and notice texts when `Cargo.lock` changes. Full
`cargo metadata --locked --format-version 1` output contains local paths and
must remain private; only the four public package fields belong in the inventory.
