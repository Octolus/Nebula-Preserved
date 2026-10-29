#pragma once

// Read-only, main-thread diagnostics for the exact ownership predicate used by
// Social V10 notifications and Public Chat V2.  This deliberately does not
// replace, relax, or short-circuit social_notifications_owned_identity().
namespace nebula_social_owned_identity_diagnostic_v2 {

struct Observation {
    bool main_thread{};
    bool initialized_ready{};
    bool owner_typed{};
    bool owner_singleton_match{};
    bool network_probe_ok{};
    bool network_connected{};
    bool network_authenticated{};
    bool network_ready{};
    bool local_typed{};
    bool local_is_local_player{};
    bool local_has_authority{};
    bool social_roots_ok{};
    bool memory_typed{};
    bool info_typed{};
    bool player_typed{};
    bool player_is_local_player{};
    bool player_identity_match{};
    bool net_id_match{};
    bool slot_valid{};
    bool owner_guid_read{};
    bool info_guid_read{};
    bool player_guid_read{};
    bool guid_triple_match{};
    bool primary_account_match{};
    bool session_account_match{};
    bool account_name_match{};
    std::uint32_t local_net_id{};
    std::uint32_t info_net_id{};
    char owner_guid_sha256[65]{};
    char info_guid_sha256[65]{};
    char player_guid_sha256[65]{};
};

bool hash_text(const char* value, char out[65]) {
    static constexpr char hex[] = "0123456789abcdef";
    if (!value || !value[0]) return false;
    BCRYPT_ALG_HANDLE algorithm{};
    BCRYPT_HASH_HANDLE hash{};
    DWORD object_size = 0, received = 0;
    UCHAR object[512]{}, digest[32]{};
    bool ok = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0 &&
              BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                                reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size),
                                &received, 0) >= 0 && object_size <= sizeof(object) &&
              BCryptCreateHash(algorithm, &hash, object, object_size, nullptr, 0, 0) >= 0 &&
              BCryptHashData(hash, reinterpret_cast<PUCHAR>(const_cast<char*>(value)),
                             static_cast<ULONG>(std::strlen(value)), 0) >= 0 &&
              BCryptFinishHash(hash, digest, sizeof(digest), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    SecureZeroMemory(object, sizeof(object));
    if (!ok) {
        SecureZeroMemory(digest, sizeof(digest));
        return false;
    }
    for (std::size_t index = 0; index < sizeof(digest); ++index) {
        out[index * 2] = hex[digest[index] >> 4];
        out[index * 2 + 1] = hex[digest[index] & 0x0f];
    }
    out[64] = 0;
    SecureZeroMemory(digest, sizeof(digest));
    return true;
}

Observation observe(void* owner) {
    Observation result{};
    result.main_thread = GetCurrentThreadId() == thread;
    result.initialized_ready = initialized && !disabled;
    result.owner_typed = typed(owner, "PS4Info", "", true);
    void* ps4_class = klass(script_image, "", "PS4Info");
    result.owner_singleton_match = result.owner_typed && ps4_class &&
        singleton(ps4_class, "_singleton") == owner;

    void* local = nullptr;
    const auto network = observe_network(local);
    result.network_probe_ok = network.probe_ok;
    result.network_connected = network.connected;
    result.network_authenticated = network.authenticated;
    result.network_ready = network.ready && network.connection_ready;
    result.local_typed = typed(local, "NetworkIdentity", "Mirror", true);
    if (result.local_typed) {
        result.local_is_local_player = field<std::uint8_t>(local, 0x1a) != 0;
        result.local_has_authority = field<std::uint8_t>(local, 0x1b) != 0;
        result.local_net_id = field<std::uint32_t>(local, 0x28);
    }

    void* manager = nullptr;
    void* social = nullptr;
    const char* roots_reason = nullptr;
    result.social_roots_ok = social_roots(manager, social, roots_reason);
    (void)social;
    (void)roots_reason;
    void* memory = result.social_roots_ok ? field<void*>(manager, 0x2c0) : nullptr;
    result.memory_typed = typed(memory, "Memory", "Assets.Scripts.Memories");
    void* info = result.memory_typed ? field<void*>(memory, 0x10) : nullptr;
    result.info_typed = typed(info, "PlayerInfo", "Assets.Scripts.Memories");
    void* player = result.info_typed ? field<void*>(info, 0x30) : nullptr;
    result.player_typed = typed(player, "NebulaPlayer", "", true);
    if (result.info_typed) result.info_net_id = field<std::uint32_t>(info, 0x10);
    if (result.player_typed) {
        result.player_is_local_player = field<std::uint8_t>(player, 0x9c) != 0;
        result.player_identity_match = field<void*>(player, 0xf8) == local;
    }
    result.net_id_match = result.local_typed && result.info_typed &&
                          result.local_net_id == result.info_net_id;

    wchar_t slot[4]{};
    const DWORD slot_length = GetEnvironmentVariableW(
        L"NEBULA_PRESERVATION_TEST_SLOT", slot, static_cast<DWORD>(std::size(slot)));
    const bool slot_one = slot_length == 1 && slot[0] == L'1';
    const bool slot_two = slot_length == 1 && slot[0] == L'2';
    result.slot_valid = slot_one || slot_two;
    const char* expected_account = slot_one ? "local-preservation-test-1" :
                                   slot_two ? "local-preservation-test-2" : nullptr;
    const char* expected_name = slot_one ? "[TEST] Preservation Client 1" :
                                slot_two ? "[TEST] Preservation Client 2" : nullptr;

    char owner_guid[257]{}, info_guid[257]{}, player_guid[257]{};
    char primary[65]{}, session[65]{}, name[65]{};
    result.owner_guid_read = result.owner_typed &&
        managed_string(field<void*>(owner, 0xe8), owner_guid, sizeof(owner_guid)) && owner_guid[0];
    result.info_guid_read = result.info_typed &&
        managed_string(field<void*>(info, 0x18), info_guid, sizeof(info_guid)) && info_guid[0];
    result.player_guid_read = result.player_typed &&
        managed_string(field<void*>(player, 0xa0), player_guid, sizeof(player_guid)) && player_guid[0];
    if (result.owner_guid_read) hash_text(owner_guid, result.owner_guid_sha256);
    if (result.info_guid_read) hash_text(info_guid, result.info_guid_sha256);
    if (result.player_guid_read) hash_text(player_guid, result.player_guid_sha256);
    result.guid_triple_match = result.owner_guid_read && result.info_guid_read &&
        result.player_guid_read && !std::strcmp(owner_guid, info_guid) &&
        !std::strcmp(owner_guid, player_guid);

    const bool primary_read = result.owner_typed &&
        managed_string(field<void*>(owner, 0x28), primary, sizeof(primary));
    const bool session_read = result.owner_typed &&
        managed_string(field<void*>(owner, 0xd8), session, sizeof(session));
    const bool name_read = result.owner_typed &&
        managed_string(field<void*>(owner, 0xe0), name, sizeof(name));
    result.primary_account_match = expected_account && primary_read &&
                                   !std::strcmp(primary, expected_account);
    result.session_account_match = expected_account && session_read &&
                                   !std::strcmp(session, expected_account);
    result.account_name_match = expected_name && name_read && !std::strcmp(name, expected_name);

    SecureZeroMemory(owner_guid, sizeof(owner_guid));
    SecureZeroMemory(info_guid, sizeof(info_guid));
    SecureZeroMemory(player_guid, sizeof(player_guid));
    SecureZeroMemory(primary, sizeof(primary));
    SecureZeroMemory(session, sizeof(session));
    SecureZeroMemory(name, sizeof(name));
    SecureZeroMemory(slot, sizeof(slot));
    return result;
}

void snapshot(Json& json, void* owner) {
    const Observation value = observe(owner);
    json.append(",\"social_owned_identity_diagnostic_v2\":{");
#define NEBULA_DIAG_BOOL(name) json.append("\"" #name "\":"); json.boolean(value.name)
    NEBULA_DIAG_BOOL(main_thread);
#define NEBULA_DIAG_MORE(name) json.append(",\"" #name "\":"); json.boolean(value.name)
    NEBULA_DIAG_MORE(initialized_ready);
    NEBULA_DIAG_MORE(owner_typed);
    NEBULA_DIAG_MORE(owner_singleton_match);
    NEBULA_DIAG_MORE(network_probe_ok);
    NEBULA_DIAG_MORE(network_connected);
    NEBULA_DIAG_MORE(network_authenticated);
    NEBULA_DIAG_MORE(network_ready);
    NEBULA_DIAG_MORE(local_typed);
    NEBULA_DIAG_MORE(local_is_local_player);
    NEBULA_DIAG_MORE(local_has_authority);
    NEBULA_DIAG_MORE(social_roots_ok);
    NEBULA_DIAG_MORE(memory_typed);
    NEBULA_DIAG_MORE(info_typed);
    NEBULA_DIAG_MORE(player_typed);
    NEBULA_DIAG_MORE(player_is_local_player);
    NEBULA_DIAG_MORE(player_identity_match);
    NEBULA_DIAG_MORE(net_id_match);
    NEBULA_DIAG_MORE(slot_valid);
    NEBULA_DIAG_MORE(owner_guid_read);
    NEBULA_DIAG_MORE(info_guid_read);
    NEBULA_DIAG_MORE(player_guid_read);
    NEBULA_DIAG_MORE(guid_triple_match);
    NEBULA_DIAG_MORE(primary_account_match);
    NEBULA_DIAG_MORE(session_account_match);
    NEBULA_DIAG_MORE(account_name_match);
#undef NEBULA_DIAG_MORE
#undef NEBULA_DIAG_BOOL
    json.append(",\"local_net_id\":"); json.integer(value.local_net_id);
    json.append(",\"info_net_id\":"); json.integer(value.info_net_id);
    json.append(",\"owner_guid_sha256\":");
    if (value.owner_guid_sha256[0]) json.string(value.owner_guid_sha256); else json.append("null");
    json.append(",\"info_guid_sha256\":");
    if (value.info_guid_sha256[0]) json.string(value.info_guid_sha256); else json.append("null");
    json.append(",\"player_guid_sha256\":");
    if (value.player_guid_sha256[0]) json.string(value.player_guid_sha256); else json.append("null");
    json.append("}");
}

}  // namespace nebula_social_owned_identity_diagnostic_v2
