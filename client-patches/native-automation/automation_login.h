#pragma once
#include <cstring>
// Pure decision/dispatch boundary, shared with authored fake-invoker tests.
namespace nac {
struct LoginState {
    bool scene_login{},current_owner{},alive{},session_ready{},pressed{},steam_ready{},loader_ready{},method_ready{},invoked{};
};
inline const char *login_reason(const LoginState &s) {
    if(!s.scene_login)return "scene_not_login";
    if(!s.current_owner)return "ps4info_not_current";
    if(!s.alive)return "login_controller_unavailable";
    if(s.invoked)return "login_already_invoked";
    if(s.pressed)return "login_button_already_pressed";
    if(!s.session_ready)return "login_session_not_ready";
    if(!s.steam_ready)return "login_steam_not_ready";
    if(!s.loader_ready)return "login_loader_not_ready";
    if(!s.method_ready)return "login_method_guard";
    return "ready";
}
using Invoke=void *(*)(const void*,void*,void**,void**);
enum class LoginResult { Rejected, Started, Exception };
inline LoginResult dispatch_login(LoginState &s,const void *method,void *owner,Invoke invoke) {
    if(std::strcmp(login_reason(s),"ready")||!method||!owner||!invoke)
        return LoginResult::Rejected;
    s.invoked=true;
    void *exception=nullptr;
    (void)invoke(method,owner,nullptr,&exception);
    return exception?LoginResult::Exception:LoginResult::Started;
}
}
