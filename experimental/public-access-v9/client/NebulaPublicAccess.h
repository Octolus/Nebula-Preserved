#pragma once
#include <cstdint>

#if defined(_WIN32)
#define NPA_EXPORT extern "C" __declspec(dllexport)
#else
#define NPA_EXPORT extern "C"
#endif

// ABI is intentionally tiny: the PE integration redirects only reviewed
// UnityWebRequest.Get direct calls to this wrapper. No URL, token or RVA is
// accepted from a network message or process command line.
NPA_EXPORT std::uint32_t NebulaPublicAccess_AbiVersion();
NPA_EXPORT void *NebulaPublicAccess_Get(void *managed_url, const void *method_info);
