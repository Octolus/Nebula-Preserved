# Authenticated client request consumer

Development source; public native acceptance is pending. This component fixes the exact shipped Unity build, whose managed metadata does not expose `SetRequestHeader` or `set_redirectLimit`.

With no public-access configuration, the wrapper forwards the original request unchanged. With a configuration, it accepts only `http://127.0.0.1:38080` requests after the existing profile validation and hash-pinned, owned sidecar readiness check. The sidecar makes the upstream HTTPS request, validates the configured CA and hostname, adds the account Authorization header, disables redirects, and rejects every upstream redirect response. The account secret is never given to Unity or placed in a URL.

Configured direct HTTPS is unsupported and fails closed. Public connections require the matching remote profile and sidecar. The native wrapper intentionally does not guess stripped managed methods or engine offsets. The local game must also use the complete 70-application-request patch inventory; the earlier 69-site profile omitted the central account producer.

Build with CMake Release and set `NEBULA_REMOTE_TRANSPORT_SHA256` to the reviewed sidecar digest. A sidecar rebuild requires a matching wrapper rebuild and release manifest; these files must be distributed together. The currently reproduced wrapper is `d0a37cfd1e47e9ec706d92c8b29dd9b29a4cfc9ca5c9891b0f427ba2510a93aa`, bound to sidecar `cfda7d033e93fe78a8150c6a11a6f3b1d66bc5e417f49ee869a0630f855c8420`.

`run_checks.py --cxx <MinGW-g++> --old-source <prior-NebulaPublicAccess.cpp> --output <new-folder>` compiles the actual consumer with local IL2CPP and sidecar interface fixtures. It creates only synthetic DPAPI test credentials. It neither loads a game/sidecar DLL nor opens a listener or connection. The old source fails the stripped-metadata regression; the new source passes ten checks. This proves the request consumer logic, not an end-to-end native TLS session.

Controls, cursor, rendering, game menus and gameplay code are outside this component.
