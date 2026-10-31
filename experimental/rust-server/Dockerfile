# Build from the repository root; Dockerfile.dockerignore limits the context.
FROM rust:1.99.0-bookworm@sha256:114c7a4425406451c2866b6aafe69fe29b1b298832db1277d411ac73c82d04d6 AS build
WORKDIR /build/experimental/rust-server
COPY experimental/rust-server/Cargo.toml experimental/rust-server/Cargo.lock ./
COPY experimental/rust-server/src/ ./src/
COPY experimental/rust-server/tests/ ./tests/
RUN cargo build --locked --release

# The candidate links against Bookworm's libc, libm and libgcc runtime.
FROM debian:bookworm-slim@sha256:7ff6ba31527b9e336162fa061746c366c4b2032f4d2cff2078bea43f78efe3f8 AS runtime
LABEL org.opencontainers.image.title="Nebula Preserved experimental Rust server" \
      org.opencontainers.image.description="Isolated candidate; native-client networking parity unproven"
RUN install -d -o 10001 -g 10001 /var/lib/nebula-rust /opt/nebula/protocol /usr/share/licenses/nebula-preserved
COPY --from=build /build/experimental/rust-server/target/release/nebula-preserved-server /usr/local/bin/nebula-preserved-server
COPY protocol/ /opt/nebula/protocol/
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/licenses/nebula-preserved/
COPY docs/LICENSING.md /usr/share/licenses/nebula-preserved/LICENSING.md
COPY experimental/rust-server/DEPENDENCIES.json /usr/share/licenses/nebula-preserved/rust-server/DEPENDENCIES.json
COPY experimental/rust-server/licenses/ /usr/share/licenses/nebula-preserved/rust-server/licenses/
WORKDIR /opt/nebula
USER 10001:10001
STOPSIGNAL SIGINT
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD ["/usr/local/bin/nebula-preserved-server", "health"]
ENTRYPOINT ["/usr/local/bin/nebula-preserved-server"]
CMD ["serve", "--bind", "127.0.0.1:8088", "--state-dir", "/var/lib/nebula-rust", "--protocol-dir", "/opt/nebula/protocol"]
