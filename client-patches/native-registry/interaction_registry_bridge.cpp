#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#include "interaction_registry_bridge_abi.h"

namespace {

constexpr uint32_t kAbi = 1;
constexpr uint8_t kExpectedBaseSha[32] = {
    0xec,0x6f,0x90,0x9d,0x3a,0xf3,0x5c,0x89,0xcd,0x28,0x7a,0x28,0x03,0xb8,0x68,0x39,
    0xcd,0x5d,0x1b,0x16,0x8b,0xc1,0xf7,0x65,0x17,0xee,0xd2,0x49,0x4c,0x85,0xe0,0x1b};

struct Il2CppString { void *klass; void *monitor; int32_t length; wchar_t chars[1]; };
struct Il2CppArray { void *klass; void *monitor; void *bounds; uintptr_t length; void *items[1]; };
struct Il2CppFloatArray { void *klass; void *monitor; void *bounds; uintptr_t length; float items[1]; };
struct Il2CppList { void *klass; void *monitor; Il2CppArray *items; int32_t size; int32_t version; };
struct Vec3 { float x, y, z; };

// HousingFurnishing.ServerData is a value type passed by address in RDX on
// Windows x64. The first five references are the authoritative compact
// ground/floor snapshot written by SaveAtServer before 0x6BEC57.
struct HousingServerData {
    Il2CppArray *assets_id;
    Il2CppFloatArray *position_x;
    Il2CppFloatArray *position_y;
    Il2CppFloatArray *position_z;
    Il2CppFloatArray *rotation_y;
    void *wall_assets_id;
    void *wall_assets_slot;
    void *ceiling_assets_id;
    void *ceiling_assets_slot;
    void *tablename;
};
static_assert(sizeof(HousingServerData) == 0x50);

using GetSingleton = void *(*)(void *);
using ComponentGetTransform = void *(*)(void *, void *);
using ComponentGetGameObject = void *(*)(void *, void *);
using TransformGetParent = void *(*)(void *, void *);
using TransformGetSiblingIndex = int32_t (*)(void *, void *);
using GameObjectGetComponentsInternal = Il2CppArray *(*)(void *, void *, bool, bool, bool, bool, void *, void *);
using ComponentGetComponent = void *(*)(void *, void *);
using SceneManagerGetActiveScene = int32_t (*)(void *);
using SceneGetName = Il2CppString *(*)(int32_t *, void *);
using SceneGetRoots = Il2CppArray *(*)(int32_t *, void *);
using ObjectGetName = Il2CppString *(*)(void *, void *);
using TransformGetVec3 = void (*)(Vec3 *, void *, void *);
using StringNewUtf16 = Il2CppString *(*)(const wchar_t *, int32_t);
using TcpSend = void (*)(void *, Il2CppString *, void *);
using ObjectGetClass = void *(*)(void *);
using ClassGetName = const char *(*)(void *);
using ClassGetNamespace = const char *(*)(void *);
using ClassGetParent = void *(*)(void *);
using ClassGetType = const void *(*)(void *);
using TypeGetObject = void *(*)(const void *);
using InitializeRuntimeMetadata = void (*)(void **);

struct Api {
    uintptr_t base{};
    GetSingleton manager{};
    GetSingleton info{};
    ComponentGetTransform component_transform{};
    ComponentGetGameObject component_game_object{};
    TransformGetParent transform_parent{};
    TransformGetSiblingIndex sibling_index{};
    GameObjectGetComponentsInternal get_components_internal{};
    ComponentGetComponent get_component_in_parent{};
    SceneManagerGetActiveScene active_scene{};
    SceneGetName scene_name{};
    SceneGetRoots scene_roots{};
    ObjectGetName object_name{};
    TransformGetVec3 position{};
    TransformGetVec3 euler{};
    StringNewUtf16 string_new_utf16{};
    TcpSend tcp_send{};
    ObjectGetClass object_get_class{};
    ClassGetName class_get_name{};
    ClassGetNamespace class_get_namespace{};
    ClassGetParent class_get_parent{};
    ClassGetType class_get_type{};
    TypeGetObject type_get_object{};
    InitializeRuntimeMetadata initialize_runtime_metadata{};
};

struct Entry {
    void *component{};
    uint32_t kind{};
    int32_t send_id{-1};
    int32_t receive_id{-1};
    std::string anchor;
    std::vector<int32_t> path;
    std::string class_name;
    int32_t slot{-1};
    int32_t ground_index{-1};
    std::string item_id;
};

struct Ground {
    std::string item_id;
    int32_t index{};
    Vec3 position{};
    float rotation{};
    void *transform{};
};

Api g_api;
bool g_initialized = false;
std::atomic<uint64_t> g_sequence{0};
std::vector<Entry> g_initial;
std::vector<Entry> g_load;
std::vector<Entry> g_save;
void *g_last_housing_owner = nullptr;
bool g_open[4]{};
bool g_failed[4]{};
bool g_initial_committed = false;
std::string g_owner_scene;
bool g_handoff_valid = false;
bool g_initial_owner_valid = false;

struct SaveSnapshot {
    bool valid{};
    void *owner{};
    std::string scene_name;
    Il2CppList *ground_list{};
    Il2CppList *floor_list{};
    int32_t ground_count{};
    int32_t floor_count{};
    std::vector<Ground> grounds;
};
SaveSnapshot g_save_snapshot;

template <class T> T at(uintptr_t rva) { return reinterpret_cast<T>(g_api.base + rva); }

template <class T> T exported(HMODULE module, const char *name) {
    FARPROC raw = GetProcAddress(module, name);
    T value{};
    static_assert(sizeof(value) == sizeof(raw));
    std::memcpy(&value, &raw, sizeof(value));
    return value;
}

std::vector<Entry> &pending(uint32_t source) {
    if (source == NEBULA_REGISTRY_INITIAL) return g_initial;
    if (source == NEBULA_REGISTRY_HOUSING_LOAD) return g_load;
    return g_save;
}

std::string utf8(Il2CppString *value) {
    if (!value || value->length < 0 || value->length > 32768) return {};
    if (!value->length) return {};
    int needed = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value->chars, value->length,
                                     nullptr, 0, nullptr, nullptr);
    if (needed <= 0) return {};
    std::string out(static_cast<size_t>(needed), '\0');
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value->chars, value->length,
                            out.data(), needed, nullptr, nullptr) != needed) return {};
    return out;
}

std::string json_string(const std::string &value) {
    static constexpr char hex[] = "0123456789abcdef";
    std::string out = "\"";
    for (unsigned char c : value) {
        switch (c) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\b': out += "\\b"; break;
        case '\f': out += "\\f"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (c < 0x20) {
                out += "\\u00"; out.push_back(hex[c >> 4]); out.push_back(hex[c & 15]);
            } else out.push_back(static_cast<char>(c));
        }
    }
    out.push_back('"');
    return out;
}

std::string number(float value) {
    if (value == 0.0f) value = 0.0f; // normalize negative zero
    char buffer[64];
    auto result = std::to_chars(buffer, buffer + sizeof(buffer), value, std::chars_format::general);
    if (result.ec != std::errc{}) return {};
    return std::string(buffer, result.ptr);
}

std::string base64url(const std::string &input) {
    static constexpr char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    std::string out;
    out.reserve((input.size() * 4 + 2) / 3);
    size_t i = 0;
    for (; i + 3 <= input.size(); i += 3) {
        uint32_t n = (static_cast<uint8_t>(input[i]) << 16) |
                     (static_cast<uint8_t>(input[i + 1]) << 8) |
                     static_cast<uint8_t>(input[i + 2]);
        out.push_back(alphabet[(n >> 18) & 63]); out.push_back(alphabet[(n >> 12) & 63]);
        out.push_back(alphabet[(n >> 6) & 63]); out.push_back(alphabet[n & 63]);
    }
    if (input.size() - i == 1) {
        uint32_t n = static_cast<uint8_t>(input[i]) << 16;
        out.push_back(alphabet[(n >> 18) & 63]); out.push_back(alphabet[(n >> 12) & 63]);
    } else if (input.size() - i == 2) {
        uint32_t n = (static_cast<uint8_t>(input[i]) << 16) |
                     (static_cast<uint8_t>(input[i + 1]) << 8);
        out.push_back(alphabet[(n >> 18) & 63]); out.push_back(alphabet[(n >> 12) & 63]);
        out.push_back(alphabet[(n >> 6) & 63]);
    }
    return out;
}

void *component_transform(void *component) {
    return component ? g_api.component_transform(component, nullptr) : nullptr;
}

std::vector<int32_t> full_path(void *component, void *stop_exclusive) {
    std::vector<int32_t> reversed;
    for (void *transform = component_transform(component); transform && transform != stop_exclusive;
         transform = g_api.transform_parent(transform, nullptr)) {
        int32_t index = g_api.sibling_index(transform, nullptr);
        if (index < 0) return {};
        reversed.push_back(index);
        if (reversed.size() > 128) return {};
    }
    std::reverse(reversed.begin(), reversed.end());
    return reversed;
}

std::string normalized_root_name(void *game_object) {
    std::string name = utf8(game_object ? g_api.object_name(game_object, nullptr) : nullptr);
    static const std::string suffix = "(Clone)";
    if (name.size() >= suffix.size() && name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0)
        name.resize(name.size() - suffix.size());
    return name;
}

bool bind_static_anchor(Entry &entry) {
    void *top = component_transform(entry.component);
    if (!top) return false;
    for (void *parent = g_api.transform_parent(top, nullptr); parent;
         parent = g_api.transform_parent(top, nullptr)) top = parent;
    void *top_go = g_api.component_game_object(top, nullptr);
    entry.anchor = normalized_root_name(top_go);
    if (entry.anchor.empty()) return false;
    int32_t active = g_api.active_scene(nullptr);
    Il2CppArray *roots = g_api.scene_roots(&active, nullptr);
    if (!roots || roots->length > 4096) return false;
    uintptr_t matches = 0;
    bool selected = false;
    for (uintptr_t i = 0; i < roots->length; ++i) {
        void *root = roots->items[i];
        if (normalized_root_name(root) == entry.anchor) {
            ++matches;
            if (root == top_go) selected = true;
        }
    }
    if (matches != 1 || !selected) return false;
    entry.path = full_path(entry.component, top);
    return true;
}

int32_t component_slot(void *component) {
    void *go = g_api.component_game_object(component, nullptr);
    void *klass = g_api.object_get_class(component);
    void *component_class = nullptr;
    for (int depth = 0; klass && depth < 16; ++depth) {
        const char *name = g_api.class_get_name(klass);
        const char *space = g_api.class_get_namespace(klass);
        if (name && space && std::strcmp(name, "Component") == 0 &&
            std::strcmp(space, "UnityEngine") == 0) {
            component_class = klass;
            break;
        }
        klass = g_api.class_get_parent(klass);
    }
    const void *type = component_class ? g_api.class_get_type(component_class) : nullptr;
    void *type_object = type ? g_api.type_get_object(type) : nullptr;
    // This exactly mirrors parameterless GetComponents<T> at 0x876F60, but
    // avoids its ambiguous closed-generic metadata slot: return a T[]; do not
    // recurse; include inactive components on this GameObject; no reverse/list.
    Il2CppArray *array = go && type_object ?
        g_api.get_components_internal(go, type_object, true, false, true, false, nullptr, nullptr) : nullptr;
    if (!array || array->length > 4096) return -1;
    for (uintptr_t i = 0; i < array->length; ++i) if (array->items[i] == component) return static_cast<int32_t>(i);
    return -1;
}

bool valid_list(Il2CppList *list) {
    return list && list->size >= 0 && list->size <= 4096 && list->items &&
           list->items->length >= static_cast<uintptr_t>(list->size);
}

struct OwnerLists {
    Il2CppList *ground{};
    Il2CppList *floor{};
    int32_t ground_count{};
    int32_t floor_count{};
};

bool owner_lists(void *owner, OwnerLists &out) {
    if (!owner) return false;
    // Snapshot both references and both sizes once. Do not reread owner fields
    // while validating the epoch: SaveAtServer serialized this exact ordering.
    out.ground = *reinterpret_cast<Il2CppList **>(reinterpret_cast<uint8_t *>(owner) + 0x18);
    out.floor = *reinterpret_cast<Il2CppList **>(reinterpret_cast<uint8_t *>(owner) + 0x28);
    if (!valid_list(out.ground) || !valid_list(out.floor)) return false;
    out.ground_count = out.ground->size;
    out.floor_count = out.floor->size;
    return out.ground_count <= 4096 - out.floor_count;
}

bool append_live_grounds(Il2CppList *list, int32_t count, std::vector<Ground> &result) {
    for (int32_t i = 0; i < count; ++i) {
        void *asset = list->items->items[i];
        if (!asset) return false;
        Ground ground;
        ground.index = static_cast<int32_t>(result.size());
        ground.item_id = utf8(*reinterpret_cast<Il2CppString **>(reinterpret_cast<uint8_t *>(asset) + 0x18));
        ground.transform = component_transform(asset);
        if (ground.item_id.empty() || !ground.transform) return false;
        g_api.position(&ground.position, ground.transform, nullptr);
        Vec3 angles{}; g_api.euler(&angles, ground.transform, nullptr); ground.rotation = angles.y;
        if (!std::isfinite(ground.position.x) || !std::isfinite(ground.position.y) ||
            !std::isfinite(ground.position.z) || !std::isfinite(ground.rotation)) return false;
        result.push_back(std::move(ground));
    }
    return true;
}

bool grounds_from_owner(void *owner, std::vector<Ground> &result) {
    OwnerLists lists;
    if (!owner_lists(owner, lists)) return false;
    result.clear();
    result.reserve(static_cast<size_t>(lists.ground_count + lists.floor_count));
    return append_live_grounds(lists.ground, lists.ground_count, result) &&
           append_live_grounds(lists.floor, lists.floor_count, result);
}

std::string scene();

bool grounds_from_save(void *owner, const SaveSnapshot &snapshot, std::vector<Ground> &result) {
    if (!snapshot.valid || snapshot.owner != owner || snapshot.scene_name.empty() || snapshot.scene_name != scene()) return false;
    if (!valid_list(snapshot.ground_list) || !valid_list(snapshot.floor_list) ||
        snapshot.ground_list->size != snapshot.ground_count || snapshot.floor_list->size != snapshot.floor_count)
        return false;
    const size_t expected = static_cast<size_t>(snapshot.ground_count + snapshot.floor_count);
    if (snapshot.grounds.size() != expected) return false;
    result = snapshot.grounds;
    for (size_t i = 0; i < expected; ++i) {
        Il2CppList *list = i < static_cast<size_t>(snapshot.ground_count) ? snapshot.ground_list : snapshot.floor_list;
        size_t local = i < static_cast<size_t>(snapshot.ground_count) ? i : i - static_cast<size_t>(snapshot.ground_count);
        void *asset = list->items->items[local];
        if (!asset) return false;
        std::string item_id = utf8(*reinterpret_cast<Il2CppString **>(reinterpret_cast<uint8_t *>(asset) + 0x18));
        void *transform = component_transform(asset);
        if (item_id.empty() || item_id != result[i].item_id || !transform) return false;
        result[i].index = static_cast<int32_t>(i);
        result[i].transform = transform;
    }
    return true;
}

bool is_housing_component(void *component) {
    auto method = *reinterpret_cast<void **>(g_api.base + 0x24FC3A0);
    return method && g_api.get_component_in_parent(component, method) != nullptr;
}

bool bind_ground(Entry &entry, const std::vector<Ground> &all) {
    void *transform = component_transform(entry.component);
    for (const auto &ground : all) {
        for (void *cursor = transform; cursor; cursor = g_api.transform_parent(cursor, nullptr)) {
            if (cursor == ground.transform) {
                entry.ground_index = ground.index;
                entry.item_id = ground.item_id;
                entry.path = full_path(entry.component, ground.transform);
                return true;
            }
        }
    }
    return false;
}

void *local_interactor() {
    void *manager = g_api.manager(nullptr);
    if (!manager) return nullptr;
    void *a = *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(manager) + 0x2C0);
    void *b = a ? *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(a) + 0x10) : nullptr;
    void *c = b ? *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(b) + 0x30) : nullptr;
    return c ? *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(c) + 0x50) : nullptr;
}

int32_t receive_index(void *component) {
    void *interactor = local_interactor();
    auto *list = interactor ? *reinterpret_cast<Il2CppList **>(reinterpret_cast<uint8_t *>(interactor) + 0x30) : nullptr;
    if (!list || list->size < 0 || list->size > 65536 || !list->items || list->items->length < static_cast<uintptr_t>(list->size)) return -1;
    for (int32_t i = 0; i < list->size; ++i) if (list->items->items[i] == component) return i;
    return -1;
}

bool complete_entries(std::vector<Entry> &entries, uint32_t source, void *owner, std::vector<Ground> &ground_sig) {
    if (source != NEBULA_REGISTRY_INITIAL) {
        // Public scenes have no HousingFurnishing owner or LOAD callback, but
        // still need an explicit complete empty furniture epoch. Any captured
        // furniture record without an owner remains a hard failure. Personal
        // scenes with an owner always publish the complete typed ground list,
        // including the noninteractive-ground case where entries is empty.
        if (!owner) {
            if (source != NEBULA_REGISTRY_HOUSING_LOAD || !entries.empty()) return false;
            ground_sig.clear();
        } else if (source == NEBULA_REGISTRY_HOUSING_SAVE) {
            if (!grounds_from_save(owner, g_save_snapshot, ground_sig)) return false;
        } else if (!grounds_from_owner(owner, ground_sig)) return false;
    }
    for (auto &entry : entries) {
        void *klass = g_api.object_get_class(entry.component);
        const char *name = klass ? g_api.class_get_name(klass) : nullptr;
        if (!name || !*name) return false;
        entry.class_name = name;
        entry.slot = component_slot(entry.component);
        if (entry.slot < 0) return false;
        if (entry.kind == NEBULA_REGISTRY_OCCUPABLE) {
            entry.receive_id = receive_index(entry.component);
            if (entry.receive_id < 0) return false;
        } else entry.receive_id = entry.send_id;
        if (source == NEBULA_REGISTRY_INITIAL) {
            if (!bind_static_anchor(entry)) return false;
            entry.ground_index = -1; entry.item_id.clear();
        } else {
            entry.anchor.clear();
            if (!bind_ground(entry, ground_sig)) return false;
        }
    }
    std::sort(entries.begin(), entries.end(), [](const Entry &a, const Entry &b) {
        if (a.kind != b.kind) return a.kind < b.kind;
        return a.send_id < b.send_id;
    });
    for (size_t i = 1; i < entries.size(); ++i)
        if (entries[i-1].kind == entries[i].kind && entries[i-1].send_id == entries[i].send_id) return false;
    return true;
}

std::string scene() {
    int32_t active = g_api.active_scene(nullptr);
    return utf8(g_api.scene_name(&active, nullptr));
}

void clear_save_snapshot() { g_save_snapshot = SaveSnapshot{}; }

bool capture_save_snapshot(void *server_data, void *owner) {
    if (!server_data || !owner) return false;
    auto *data = reinterpret_cast<HousingServerData *>(server_data);
    if (!data->assets_id || !data->position_x || !data->position_y ||
        !data->position_z || !data->rotation_y) return false;
    const uintptr_t count = data->assets_id->length;
    if (count > 4096 || data->position_x->length != count || data->position_y->length != count ||
        data->position_z->length != count || data->rotation_y->length != count) return false;
    OwnerLists lists;
    if (!owner_lists(owner, lists) || count != static_cast<uintptr_t>(lists.ground_count + lists.floor_count)) return false;
    SaveSnapshot captured;
    captured.owner = owner;
    captured.scene_name = scene();
    if (captured.scene_name.empty()) return false;
    captured.ground_list = lists.ground;
    captured.floor_list = lists.floor;
    captured.ground_count = lists.ground_count;
    captured.floor_count = lists.floor_count;
    captured.grounds.reserve(static_cast<size_t>(count));
    for (uintptr_t i = 0; i < count; ++i) {
        Ground ground;
        ground.index = static_cast<int32_t>(i);
        ground.item_id = utf8(reinterpret_cast<Il2CppString *>(data->assets_id->items[i]));
        ground.position = {data->position_x->items[i], data->position_y->items[i], data->position_z->items[i]};
        ground.rotation = data->rotation_y->items[i];
        if (ground.item_id.empty() || !std::isfinite(ground.position.x) || !std::isfinite(ground.position.y) ||
            !std::isfinite(ground.position.z) || !std::isfinite(ground.rotation)) return false;
        // The wire contract normalizes all IEEE754 signed zero values to +0.
        if (ground.position.x == 0.0f) ground.position.x = 0.0f;
        if (ground.position.y == 0.0f) ground.position.y = 0.0f;
        if (ground.position.z == 0.0f) ground.position.z = 0.0f;
        if (ground.rotation == 0.0f) ground.rotation = 0.0f;
        captured.grounds.push_back(std::move(ground));
    }
    captured.valid = true;
    g_save_snapshot = std::move(captured);
    return true;
}

std::string guid() {
    void *info = g_api.info(nullptr);
    return info ? utf8(*reinterpret_cast<Il2CppString **>(reinterpret_cast<uint8_t *>(info) + 0xE8)) : std::string{};
}

std::string encode_json(uint32_t source, uint64_t seq, const std::vector<Entry> &entries, const std::vector<Ground> &ground_sig) {
    const char *source_name = source == NEBULA_REGISTRY_INITIAL ? "initial" :
                              source == NEBULA_REGISTRY_HOUSING_LOAD ? "load" : "save";
    std::string scene_name = scene();
    if (scene_name.empty()) return {};
    std::string out = "{\"v\":1,\"source\":" + json_string(source_name) +
                      ",\"scene\":" + json_string(scene_name) +
                      ",\"seq\":" + std::to_string(seq) + ",\"entries\":[";
    for (size_t i = 0; i < entries.size(); ++i) {
        if (i) out.push_back(',');
        const Entry &e = entries[i];
        out += "{\"kind\":" + json_string(e.kind == NEBULA_REGISTRY_GENERIC ? "generic" : "occupable") +
               ",\"send_id\":" + std::to_string(e.send_id) +
               ",\"receive_id\":" + std::to_string(e.receive_id) +
               ",\"anchor\":" + json_string(e.anchor) + ",\"path\":[";
        for (size_t j = 0; j < e.path.size(); ++j) { if (j) out.push_back(','); out += std::to_string(e.path[j]); }
        out += "],\"class\":" + json_string(e.class_name) +
               ",\"slot\":" + std::to_string(e.slot) +
               ",\"ground_index\":" + std::to_string(e.ground_index) +
               ",\"item_id\":" + json_string(e.item_id) + "}";
    }
    out += "],\"ground_sig\":[";
    for (size_t i = 0; i < ground_sig.size(); ++i) {
        if (i) out.push_back(',');
        const Ground &g = ground_sig[i];
        std::string x = number(g.position.x), y = number(g.position.y), z = number(g.position.z), r = number(g.rotation);
        if (x.empty() || y.empty() || z.empty() || r.empty()) return {};
        out += "{\"item_id\":" + json_string(g.item_id) + ",\"index\":" + std::to_string(g.index) +
               ",\"tx\":" + x + ",\"ty\":" + y + ",\"tz\":" + z + ",\"r\":" + r + "}";
    }
    out += "]}";
    return out;
}

bool send_registry(uint32_t source, std::vector<Entry> entries, void *owner) {
    std::vector<Ground> ground_sig;
    if (!complete_entries(entries, source, owner, ground_sig)) return false;
    uint64_t seq = g_sequence.fetch_add(1, std::memory_order_relaxed);
    std::string body = encode_json(source, seq, entries, ground_sig);
    std::string session = guid();
    constexpr size_t kChunkBytes = 4096;
    constexpr size_t kMaxParts = 256;
    constexpr size_t kMaxBody = kChunkBytes * kMaxParts;
    if (body.empty() || session.empty() || body.size() > kMaxBody) return false;
    size_t parts = (body.size() + kChunkBytes - 1) / kChunkBytes;
    if (!parts || parts > kMaxParts) return false;
    void *manager = g_api.manager(nullptr);
    void *tcp = manager ? *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(manager) + 0x2B8) : nullptr;
    if (!tcp) return false;
    for (size_t part = 0; part < parts; ++part) {
        size_t offset = part * kChunkBytes;
        std::string chunk = body.substr(offset, std::min(kChunkBytes, body.size() - offset));
        std::string wire = "97#" + session + "#" + std::to_string(seq) + "#" +
                           std::to_string(part) + "#" + std::to_string(parts) + "#" + base64url(chunk);
        // 4096 decoded bytes expand to at most 5462 base64url characters,
        // leaving ample space below the shipped Telepathy 0x4000-byte cap.
        if (wire.size() >= 0x3F00) return false;
        int wide_len = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, wire.data(), static_cast<int>(wire.size()), nullptr, 0);
        if (wide_len <= 0) return false;
        std::wstring wide(static_cast<size_t>(wide_len), L'\0');
        if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, wire.data(), static_cast<int>(wire.size()),
                                wide.data(), wide_len) != wide_len) return false;
        Il2CppString *managed = g_api.string_new_utf16(wide.data(), wide_len);
        if (!managed) return false;
        g_api.tcp_send(tcp, managed, nullptr);
    }
    return true;
}

} // namespace

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(module);
    return TRUE;
}

NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_AbiVersion(void) { return kAbi; }

NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_Initialize(const NebulaRegistryHostV1 *host) {
    try {
        if (g_initialized) return 1;
        if (!host || host->size != sizeof(*host) || host->abi_version != kAbi || !host->game_assembly_base ||
            std::memcmp(host->game_assembly_sha256, kExpectedBaseSha, sizeof(kExpectedBaseSha)) != 0) return 0;
        g_api.base = host->game_assembly_base;
        HMODULE game = reinterpret_cast<HMODULE>(host->game_assembly_base);
        g_api.manager = at<GetSingleton>(0x43CDF0); g_api.info = at<GetSingleton>(0x423490);
        g_api.component_transform = at<ComponentGetTransform>(0x1B85F10);
        g_api.component_game_object = at<ComponentGetGameObject>(0x1B85ED0);
        g_api.transform_parent = at<TransformGetParent>(0x1B97190);
        g_api.sibling_index = at<TransformGetSiblingIndex>(0x1B97210);
        g_api.get_components_internal = at<GameObjectGetComponentsInternal>(0x1B87670);
        g_api.get_component_in_parent = at<ComponentGetComponent>(0x8658E0);
        g_api.active_scene = at<SceneManagerGetActiveScene>(0x1BAB240);
        g_api.scene_name = at<SceneGetName>(0x1BACAC0);
        g_api.scene_roots = at<SceneGetRoots>(0x1BAC930);
        g_api.object_name = at<ObjectGetName>(0x1B8C010);
        g_api.position = at<TransformGetVec3>(0x1B991E0); g_api.euler = at<TransformGetVec3>(0x1B98C70);
        g_api.tcp_send = at<TcpSend>(0x5E7820);
        g_api.initialize_runtime_metadata = at<InitializeRuntimeMetadata>(0x287160);
        g_api.string_new_utf16 = exported<StringNewUtf16>(game, "il2cpp_string_new_utf16");
        g_api.object_get_class = exported<ObjectGetClass>(game, "il2cpp_object_get_class");
        g_api.class_get_name = exported<ClassGetName>(game, "il2cpp_class_get_name");
        g_api.class_get_namespace = exported<ClassGetNamespace>(game, "il2cpp_class_get_namespace");
        g_api.class_get_parent = exported<ClassGetParent>(game, "il2cpp_class_get_parent");
        g_api.class_get_type = exported<ClassGetType>(game, "il2cpp_class_get_type");
        g_api.type_get_object = exported<TypeGetObject>(game, "il2cpp_type_get_object");
        if (!g_api.string_new_utf16 || !g_api.object_get_class || !g_api.class_get_name ||
            !g_api.class_get_namespace || !g_api.class_get_parent || !g_api.class_get_type ||
            !g_api.type_get_object) return 0;
        g_api.initialize_runtime_metadata(reinterpret_cast<void **>(g_api.base + 0x24FC3A0));
        if (!*reinterpret_cast<void **>(g_api.base + 0x24FC3A0)) return 0;
        g_initialized = true;
        return 1;
    } catch (...) { return 0; }
}

NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_Begin(uint32_t source, void *owner) {
    try {
        if (!g_initialized || source < NEBULA_REGISTRY_INITIAL || source > NEBULA_REGISTRY_HOUSING_LOAD) return 0;
        clear_save_snapshot();
        pending(source).clear();
        if (source == NEBULA_REGISTRY_INITIAL) {
            g_load.clear();
            g_open[NEBULA_REGISTRY_HOUSING_LOAD] = false;
            g_failed[NEBULA_REGISTRY_HOUSING_LOAD] = false;
            g_initial_committed = false;
            const bool fresh_handoff = g_handoff_valid && !g_owner_scene.empty() && g_owner_scene == scene();
            // A successful LOAD grants exactly one INITIAL epoch permission to
            // retain its owner. Consume it here, not at Commit: an aborted
            // INITIAL scan must not let a later scan reuse the raw pointer.
            g_handoff_valid = false;
            g_initial_owner_valid = fresh_handoff;
            if (!fresh_handoff) {
                g_last_housing_owner = nullptr;
                g_owner_scene.clear();
            }
        } else {
            g_handoff_valid = false;
            g_initial_owner_valid = false;
            g_last_housing_owner = owner;
            g_owner_scene = scene();
        }
        g_failed[source] = false;
        g_open[source] = true;
        return 1;
    } catch (...) {
        if (source <= NEBULA_REGISTRY_HOUSING_LOAD) {
            pending(source).clear(); g_open[source] = false; g_failed[source] = false;
        }
        g_last_housing_owner = nullptr; g_owner_scene.clear();
        g_handoff_valid = false;
        g_initial_owner_valid = false;
        return 0;
    }
}

NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_CaptureSave(void *server_data, void *owner) {
    try {
        if (!g_initialized || !g_open[NEBULA_REGISTRY_HOUSING_SAVE] ||
            g_failed[NEBULA_REGISTRY_HOUSING_SAVE] || !capture_save_snapshot(server_data, owner)) {
            clear_save_snapshot();
            g_failed[NEBULA_REGISTRY_HOUSING_SAVE] = true;
            return 0;
        }
        return 1;
    } catch (...) {
        clear_save_snapshot();
        g_failed[NEBULA_REGISTRY_HOUSING_SAVE] = true;
        return 0;
    }
}

NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_Record(void *component, uint32_t kind, uint32_t source,
                                                     int32_t send_id, void *owner) {
    try {
        if (!g_initialized || source < NEBULA_REGISTRY_INITIAL || source > NEBULA_REGISTRY_HOUSING_LOAD) return 0;
        if (!g_open[source] || !component || send_id < 0 ||
            (kind != NEBULA_REGISTRY_GENERIC && kind != NEBULA_REGISTRY_OCCUPABLE) ||
            (source != NEBULA_REGISTRY_INITIAL && !owner)) {
            g_failed[source] = true;
            if (source != NEBULA_REGISTRY_INITIAL) {
                g_last_housing_owner = nullptr; g_owner_scene.clear();
                g_handoff_valid = false; g_initial_owner_valid = false;
                if (source == NEBULA_REGISTRY_HOUSING_SAVE) clear_save_snapshot();
            }
            return 0;
        }
        if (source != NEBULA_REGISTRY_INITIAL && owner) g_last_housing_owner = owner;
        Entry entry;
        entry.component = component; entry.kind = kind; entry.send_id = send_id;
        // OnConnected scans every active object. If durable furniture loaded
        // first, this scan overwrites its component send IDs. Rebind those
        // records into the separate housing namespace and republish it at the
        // initial commit instead of incorrectly admitting them as static keys.
        if (source == NEBULA_REGISTRY_INITIAL && is_housing_component(component))
            g_load.push_back(std::move(entry));
        else
            pending(source).push_back(std::move(entry));
        return 1;
    } catch (...) {
        if (source <= NEBULA_REGISTRY_HOUSING_LOAD) g_failed[source] = true;
        if (source != NEBULA_REGISTRY_INITIAL) {
            g_last_housing_owner = nullptr; g_owner_scene.clear();
            g_handoff_valid = false; g_initial_owner_valid = false;
            if (source == NEBULA_REGISTRY_HOUSING_SAVE) clear_save_snapshot();
        }
        return 0;
    }
}

NEBULA_BRIDGE_EXPORT uint32_t NebulaRegistry_Commit(uint32_t source, void *owner) {
    try {
        if (!g_initialized || source < NEBULA_REGISTRY_INITIAL || source > NEBULA_REGISTRY_HOUSING_LOAD || !g_open[source]) return 0;
        if (source != NEBULA_REGISTRY_INITIAL && owner) g_last_housing_owner = owner;
        auto &records = pending(source);
        bool ok = !g_failed[source] && send_registry(source, records, owner);
        records.clear();
        if (source == NEBULA_REGISTRY_HOUSING_SAVE) clear_save_snapshot();
        if (ok && source == NEBULA_REGISTRY_INITIAL) {
            if (g_initial_owner_valid && g_last_housing_owner) {
                // Publish even when no interactive furniture was captured: the
                // ground signature itself is part of completeness.
                ok = send_registry(NEBULA_REGISTRY_HOUSING_LOAD, g_load, g_last_housing_owner);
            } else {
                // Public scenes explicitly publish empty entries+ground_sig.
                // Missing owner plus captured furniture cannot take this path.
                ok = g_load.empty() &&
                     send_registry(NEBULA_REGISTRY_HOUSING_LOAD, g_load, nullptr);
            }
        }
        if (source == NEBULA_REGISTRY_INITIAL) g_load.clear();
        if (source == NEBULA_REGISTRY_INITIAL) {
            g_initial_committed = ok;
            g_last_housing_owner = nullptr; g_owner_scene.clear();
            g_handoff_valid = false; g_initial_owner_valid = false;
        } else if (source == NEBULA_REGISTRY_HOUSING_LOAD && ok && !g_initial_committed) {
            g_handoff_valid = true;
            g_initial_owner_valid = false;
        } else {
            g_last_housing_owner = nullptr; g_owner_scene.clear();
            g_handoff_valid = false; g_initial_owner_valid = false;
        }
        g_failed[source] = false;
        g_open[source] = false;
        return ok ? 1u : 0u;
    } catch (...) {
        pending(source).clear();
        if (source == NEBULA_REGISTRY_INITIAL) g_load.clear();
        if (source == NEBULA_REGISTRY_HOUSING_SAVE) clear_save_snapshot();
        g_last_housing_owner = nullptr;
        g_owner_scene.clear();
        g_handoff_valid = false;
        g_initial_owner_valid = false;
        if (source <= NEBULA_REGISTRY_HOUSING_LOAD) { g_failed[source] = false; g_open[source] = false; }
        return 0;
    }
}
