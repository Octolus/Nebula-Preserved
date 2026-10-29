# Nebula Public Access remote-v9

This source is the direct-TLS variant of the reviewed public-access wrapper.
Direct requests to the configured HTTPS origin preserve the v8 behavior:
redirects are disabled before the exact per-account Authorization header is
attached. Requests to the fixed remote-profile origin
`http://127.0.0.1:38080` instead start and wait for the hash-pinned sibling
transport before calling the original `UnityWebRequest.Get`.

The sibling pin is a mandatory CMake input:

```text
-DNEBULA_REMOTE_TRANSPORT_SHA256=<64 lowercase hex>
```

Configuration fails if the pin is absent or malformed. The resulting helper
is statically linked and may import only reviewed Windows system DLLs. The
release composer must validate its exact imports/exports and install both the
sidecar and helper before the importing GameAssembly.

Startup is lazy and occurs only from the reviewed Get wrapper, never from
`DllMain`. The helper validates:

- exact original `Nebula Realms.exe` SHA-256;
- exact sibling executable SHA-256 while holding a no-write/no-delete handle;
- exact LF-only `remote-game.conf` schema and remote HTTPS origin equality;
- fixed local API and scene-port range;
- direct-child CA path and exact CA SHA-256.

It creates a manual-reset readiness event containing the game PID and process
creation FILETIME, creates the sidecar suspended and with no arguments, assigns
it to a kill-on-close job, resumes it, then waits at most five seconds. Failure
terminates the owned job and permanently fails loopback requests for that game
process. The successful job handle intentionally remains open until Windows
closes the game process handle table; the sidecar also monitors the exact
parent process and has its own bounded lifetime.

No target client, listener or service was run by this source stage.
