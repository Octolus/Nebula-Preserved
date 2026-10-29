#pragma once
#include <cstring>
#include "automation_login.h"
// Pure guard/dispatch boundary; no target object or retained Unity reference.
namespace nac {
struct NetworkState {
    bool probe_ok{},connected{},ready{},local_player_alive{},authenticated{},connection_ready{};
};
inline const char *network_reason(const NetworkState &s) {
    if(!s.probe_ok)return "mirror_probe_unavailable";
    if(!s.connected)return "mirror_not_connected";
    if(!s.ready)return "mirror_not_ready";
    if(!s.local_player_alive)return "mirror_local_player_unavailable";
    if(!s.authenticated)return "mirror_not_authenticated";
    if(!s.connection_ready)return "mirror_connection_not_ready";
    return "ready";
}
struct WardrobeState {
    bool scene_world{},current_owner{},in_space{},manager_alive{},local_player_done{},travelling{},open{};
    bool local_player_ready{},pad_ready{},notifications_ready{},loader_ready{},tcp_ready{},method_ready{};
    NetworkState network{};
};
inline const char *wardrobe_reason(const WardrobeState &s) {
    if(!s.scene_world)return "scene_not_allocated_world";
    if(!s.current_owner)return "ps4info_not_current";
    const char *network=network_reason(s.network);
    if(std::strcmp(network,"ready"))return network;
    if(!s.in_space)return "not_in_space";
    if(!s.manager_alive)return "manager_unavailable";
    if(!s.local_player_done)return "local_player_not_ready";
    if(s.travelling)return "manager_travelling";
    if(s.open)return "wardrobe_already_open";
    if(!s.local_player_ready)return "local_player_chain_unavailable";
    if(!s.pad_ready)return "wardrobe_pad_unavailable";
    if(!s.notifications_ready)return "wardrobe_notifications_unavailable";
    if(!s.loader_ready)return "wardrobe_loader_unavailable";
    if(!s.tcp_ready)return "wardrobe_tcp_unavailable";
    if(!s.method_ready)return "wardrobe_method_guard";
    return "ready";
}
enum class WardrobeResult { Rejected, Started, Exception };
inline WardrobeResult dispatch_wardrobe(const WardrobeState &s,const void *method,void *owner,Invoke invoke) {
    if(std::strcmp(wardrobe_reason(s),"ready")||!method||!owner||!invoke)
        return WardrobeResult::Rejected;
    void *exception=nullptr;
    (void)invoke(method,owner,nullptr,&exception);
    return exception?WardrobeResult::Exception:WardrobeResult::Started;
}
}
