#pragma once

#include <string>

// Loads the exact remote transport profile. A false return makes configured
// public requests fail closed; unconfigured local forwarding is independent.
bool NebulaRemote_LoadProfile(const std::wstring &public_server_origin);

// The client metadata uses this fixed origin only in the remote-TLS profile.
bool NebulaRemote_IsLoopbackRequest(const std::wstring &url);

// Starts the hash-pinned sibling once, assigns it to a kill-on-close job and
// waits at most five seconds for its authenticated-listener readiness event.
bool NebulaRemote_EnsureReady();
