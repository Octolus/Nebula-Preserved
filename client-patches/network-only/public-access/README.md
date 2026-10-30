# Authenticated client request consumer

Development source; public native acceptance is pending. This component fixes the exact shipped Unity build, whose managed metadata does not expose `SetRequestHeader` or `set_redirectLimit`.

With no public-access configuration, the wrapper forwards the original request unchanged. With a configuration, it accepts only `http://127.0.0.1:38080` requests after profile validation and the hash-pinned, owned sidecar readiness check. The sidecar makes the upstream HTTPS request, validates its certificate chain and hostname, adds the account Authorization header, disables redirects, and rejects every upstream redirect response. The account secret is never given to Unity or placed in a URL.

The current candidate supports the exact seven-field v2 `trust=system` profile
for public certificates trusted by Windows. It does not require a CA file. The
exact eight-field v1 profile keeps its pinned private CA. Unknown versions,
duplicate/missing fields and mixed trust profiles fail closed. The sidecar still
performs normal signature, hostname and expiry checks for both API and gateway;
system trust does not mean accepting arbitrary TLS certificates.

Configured direct HTTPS is unsupported and fails closed. Public connections require the matching remote profile and sidecar. The native wrapper intentionally does not guess stripped managed methods or engine offsets. The local game must also use the complete 70-application-request patch inventory; the earlier 69-site profile omitted the central account producer.

Build with CMake Release and set `NEBULA_REMOTE_TRANSPORT_SHA256` to the reviewed sidecar digest. A sidecar rebuild requires a matching wrapper rebuild and release manifest; these files must be distributed together. The current headless-tested candidate wrapper is `909284bf0e351ed037ea3acc22cd06ff57d2a17c3bfb83cd02df48b4e066948f`, bound to sidecar `e5baacfc3f9ad884610bf0c32c71d9e533f8df05d69264b4aedb97041c18bde5`. It remains provisional pending native acceptance. The [validation record](../../../experimental/remote-transport/client/tls-validation.json) pins the corresponding sources and binaries.

`run_checks.py --cxx <MinGW-g++> --old-source <prior-NebulaPublicAccess.cpp> --output <new-folder>` compiles the actual consumer with local IL2CPP and sidecar interface fixtures. It creates only synthetic DPAPI test credentials. It neither loads a game/sidecar DLL nor opens a listener or connection. The old source fails the stripped-metadata regression; the new source passes ten checks. This proves the request consumer logic, not an end-to-end native TLS session.

Controls, cursor, rendering, game menus and gameplay code are outside this component.

`run_profile_checks.py --cxx <MinGW-g++> --output <new-private-folder>` compiles
the actual bootstrap profile parser and runs 23 cases, including v2 with no CA
file, legacy CA success/tamper, wrong origin, duplicate fields, invalid ports and
mixed/unknown trust. It creates only disposable synthetic files and starts no
game, sidecar or listener.
