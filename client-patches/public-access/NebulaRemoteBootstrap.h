#pragma once

#include <string>

// Loads the optional remote transport profile. A false return only means the
// direct-HTTPS profile remains active; loopback requests still fail closed.
bool NebulaRemote_LoadProfile(const std::wstring &public_server_origin);

// The client metadata uses this fixed origin only in the remote-TLS profile.
bool NebulaRemote_IsLoopbackRequest(const std::wstring &url);

// Starts the hash-pinned sibling once, assigns it to a kill-on-close job and
// waits at most five seconds for its authenticated-listener readiness event.
bool NebulaRemote_EnsureReady();
