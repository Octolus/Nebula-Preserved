#ifndef NEBULA_INTERACTION_REGISTRY_BRIDGE_ABI_H
#define NEBULA_INTERACTION_REGISTRY_BRIDGE_ABI_H

#include <stdint.h>

#if defined(_WIN32)
#define NEBULA_BRIDGE_EXPORT extern "C" __declspec(dllexport)
#else
#error This bridge ABI is defined only for the reviewed Windows x64 build.
#endif

enum NebulaRegistryKind : uint32_t {
    NEBULA_REGISTRY_GENERIC = 1,
    NEBULA_REGISTRY_OCCUPABLE = 2,
};

enum NebulaRegistrySource : uint32_t {
    NEBULA_REGISTRY_INITIAL = 1,
    NEBULA_REGISTRY_HOUSING_SAVE = 2,
    NEBULA_REGISTRY_HOUSING_LOAD = 3,
};

struct NebulaRegistryHostV1 {
    uint32_t size;
    uint32_t abi_version;
    uintptr_t game_assembly_base;
    uint8_t game_assembly_sha256[32];
};

// DllMain must only retain its module handle and return.  The patched wrapper
// calls Initialize lazily on the existing Unity/IL2CPP main thread.
NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_AbiVersion(void);
NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_Initialize(const NebulaRegistryHostV1 *host);
NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_Begin(uint32_t source, void *owner);

// Called immediately before HousingNETGcloud.Send_SavePreset at 0x6BEC57.
// server_data points to the 0x50-byte HousingFurnishing.ServerData value in
// RDX. The bridge deep-copies its compact ground/floor ID and f32 arrays before
// the original asynchronous HTTP sender runs.
NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_CaptureSave(
    void *server_data,
    void *owner);

// Call only after the original Initialize returns, so send_id is the component
// counter used by its native C2S packets. The bridge resolves a separate dense
// receive_id from NebulaInteractor.occupables at commit time; generic IDs stay
// equal. owner is null for the initial scan; the
// SaveAtServer wrappers pass their verified HousingFurnishing pointer.  The
// load callback wrappers pass [R13+0x10], the verified HousingFurnishing owner.
NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_Record(
    void *component,
    uint32_t kind,
    uint32_t source,
    int32_t send_id,
    void *owner);

// Atomically publishes a complete source epoch.  An empty pending set clears
// old state.  HOUSING_LOAD commits after the original final completion delegate.
NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_Commit(
    uint32_t source,
    void *owner);

#endif
