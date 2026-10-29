#pragma once
#include <cstdint>
#include <cstring>
namespace nebula_settings_sidebar_policy {
struct Binding {int manager{},options{},sidebar{},input{};char session[65]{};};
struct Observation {
    Binding binding{};bool original_ready{},original_open{},eligible_closed{};
    bool sidebar_open{},button_active{};
};
struct Result {const char*status;const char*code;};
struct Host {
    virtual bool capture(Observation&,const char*&) noexcept=0;
    virtual bool open_sidebar() noexcept=0;
    virtual Result open_original_settings() noexcept=0;
    virtual ~Host()=default;
};
inline bool same(const Binding&a,const Binding&b) noexcept {
    return a.manager==b.manager&&a.options==b.options&&a.sidebar==b.sidebar&&
      a.input==b.input&&!std::strcmp(a.session,b.session);
}
inline Result run(Host&host) noexcept {
    Observation before{};const char*why="settings_sidebar_context_guard";
    if(!host.capture(before,why))return {"rejected",why};
    if(!before.original_ready) {
        if(!before.eligible_closed)return {"rejected","settings_open_identity_guard"};
        if(!host.open_sidebar())return {"error","settings_sidebar_callback_exception"};
        Observation after{};
        if(!host.capture(after,why)||!same(before.binding,after.binding)||
           !after.sidebar_open||!after.button_active||!after.original_ready||after.original_open)
            return {"error","settings_sidebar_callback_readback_failed"};
    }
    auto result=host.open_original_settings();
    if(std::strcmp(result.status,"ok")&&std::strcmp(result.status,"started"))return result;
    Observation after{};
    if(!host.capture(after,why)||!same(before.binding,after.binding)||
       !after.original_ready||!after.original_open)
        return {"error","settings_owned_open_readback_failed"};
    return result;
}
}
