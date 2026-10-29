#pragma once

// Source-correct PlayerInfo.NetId access for Social V10 and Public Chat V2.
// PlayerInfo has no uint backing field at +0x10; shipped get_NetId (RVA
// 0x616a70) follows PlayerInfo.nebulaPlayer -> NetworkIdentity -> netId.
bool social_player_info_net_id_exact(void* info, void* expected_identity,
                                     std::uint32_t& value) {
    value = 0;
    if (GetCurrentThreadId() != thread || !initialized || disabled ||
        !typed(info, "PlayerInfo", "Assets.Scripts.Memories") ||
        !typed(expected_identity, "NetworkIdentity", "Mirror", true) ||
        !readable(expected_identity, 0x2c)) return false;
    void* player = field<void*>(info, 0x30);
    if (!typed(player, "NebulaPlayer", "", true) ||
        field<void*>(player, 0xf8) != expected_identity) return false;
    void* player_info_class = klass(script_image, "Assets.Scripts.Memories", "PlayerInfo");
    void* getter = method(player_info_class, "get_NetId", 0, 0x616a70);
    void* boxed = nullptr;
    if (!getter || !invoke(getter, info, nullptr, boxed) ||
        !typed(boxed, "UInt32", "System") || !readable(boxed, 0x14)) return false;
    value = field<std::uint32_t>(boxed, 0x10);
    return value != 0 && value == field<std::uint32_t>(expected_identity, 0x28);
}
