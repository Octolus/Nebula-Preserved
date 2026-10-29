#pragma once
namespace nebula::friend_request_probe {
struct Inputs { bool roots{},main_window{},loading_circle{},selected_model{},peer{},remote_username{},remote_platform{},not_already_friend{},local_sender{},tcp_client{},tcp_connected{}; };
inline const char* evaluate(const Inputs& v) {
 if(!v.roots)return "friend_preflight_roots";
 if(!v.main_window)return "friend_preflight_main_window";
 if(!v.loading_circle)return "friend_preflight_loading_circle";
 if(!v.selected_model)return "friend_preflight_selected_model";
 if(!v.peer)return "friend_preflight_peer";
 if(!v.remote_username)return "friend_preflight_remote_username";
 if(!v.remote_platform)return "friend_preflight_remote_platform";
 if(!v.not_already_friend)return "friend_preflight_already_friend";
 if(!v.local_sender)return "friend_preflight_local_sender";
 if(!v.tcp_client)return "friend_preflight_tcp_client";
 if(!v.tcp_connected)return "friend_preflight_tcp_disconnected";
 return "ready";
}
}
