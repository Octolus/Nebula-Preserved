#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include "automation_types.h"

// Pure policy/state boundary for the two fixed, original CharacterEditor UI
// workflows. Runtime discovery and all Unity calls remain in automation.cpp.
namespace nac {
constexpr unsigned kMaxRemoveRequests=1;
constexpr unsigned kMaxSaveRequests=4;
enum class HierarchyScanDisposition { ready, pending, fatal };
inline HierarchyScanDisposition hierarchy_scan_disposition(unsigned matches,const char *reason) {
    if(matches==1&&reason&&!std::strcmp(reason,"ready"))return HierarchyScanDisposition::ready;
    if(matches==0&&reason&&!std::strcmp(reason,"hierarchy_name_missing"))return HierarchyScanDisposition::pending;
    return HierarchyScanDisposition::fatal;
}
inline HierarchyScanDisposition direct_child_scan_disposition(unsigned compatible,const char *reason) {
    if(compatible==1&&reason&&!std::strcmp(reason,"ready"))return HierarchyScanDisposition::ready;
    if(compatible==0&&reason&&(!std::strcmp(reason,"direct_child_name_missing")||
                              !std::strcmp(reason,"direct_child_active_missing")))
        return HierarchyScanDisposition::pending;
    return HierarchyScanDisposition::fatal;
}

inline bool save_name_valid(const char *name) {
    if(!name)return false;
    const std::size_t n=std::strlen(name);
    if(n<1||n>16||name[0]==' '||name[n-1]==' ')return false;
    for(std::size_t i=0;i<n;++i) {
        const unsigned char c=static_cast<unsigned char>(name[i]);
        if(c<33||c>126||c=='#'||c=='/'||c=='\\')return false;
    }
    return true;
}
inline bool digest_valid(const char digest[65]) {
    if(!digest||digest[64])return false;
    for(unsigned i=0;i<64;++i)
        if(!((digest[i]>='0'&&digest[i]<='9')||(digest[i]>='a'&&digest[i]<='f')))return false;
    return true;
}
inline bool same_digest(const char a[65],const char b[65]) {
    return digest_valid(a)&&digest_valid(b)&&std::memcmp(a,b,65)==0;
}
inline bool duplicate_name(const char *target,const char names[][65],unsigned count,bool truncated) {
    if(!save_name_valid(target)||truncated||count>32)return true;
    for(unsigned i=0;i<count;++i)if(!std::strcmp(target,names[i]))return true;
    return false;
}
inline bool remove_generation_complete(bool dispatched,int pre_assets,int pre_children,
                                       int assets,int children,bool same_session) {
    return dispatched&&pre_assets>0&&pre_children>0&&assets==0&&children==0&&same_session;
}
inline bool save_generation_complete(bool dispatched,bool seen_active,bool panel_active,
                                     bool input_active,bool controls_active,bool target_exact,
                                     bool same_session) {
    return dispatched&&seen_active&&!panel_active&&!input_active&&controls_active&&target_exact&&same_session;
}

struct RemoveState {
    bool scene_editor{},current_owner{},session_same{},desktop_ok{},female{},initialized{},preset_loaded{};
    bool preset_idle{},save_idle{},current_preset_exact{};
};
inline const char *remove_context_reason(const RemoveState &s) {
    if(!s.desktop_ok)return "remove_desktop_guard";
    if(!s.scene_editor)return "remove_wrong_scene";
    if(!s.current_owner)return "remove_ps4info_not_current";
    if(!s.session_same)return "remove_session_changed";
    if(!s.female)return "remove_wrong_gender";
    if(!s.initialized||!s.preset_loaded)return "remove_editor_not_ready";
    if(!s.preset_idle||!s.save_idle)return "remove_action_overlap";
    if(!s.current_preset_exact)return "remove_wrong_preset";
    return "ready";
}

struct SaveState {
    bool scene_editor{},current_owner{},session_same{},desktop_ok{},female{},initialized{},preset_loaded{};
    bool preset_idle{},remove_idle{},remove_completed{},cache_fresh{},cache_complete{};
};
inline const char *save_context_reason(const SaveState &s) {
    if(!s.desktop_ok)return "save_desktop_guard";
    if(!s.scene_editor)return "save_wrong_scene";
    if(!s.current_owner)return "save_ps4info_not_current";
    if(!s.session_same)return "save_session_changed";
    if(!s.female)return "save_wrong_gender";
    if(!s.initialized||!s.preset_loaded)return "save_editor_not_ready";
    if(!s.preset_idle||!s.remove_idle)return "save_action_overlap";
    if(!s.remove_completed)return "save_remove_not_completed";
    if(!s.cache_fresh||!s.cache_complete)return "save_preset_preflight_unavailable";
    return "ready";
}

enum class ReferenceDispatch { rejected, started, exception };
inline ReferenceDispatch invoke_reference(const void *method,void *owner,void *managed,
                                          Invoke invoke) {
    if(!method||!owner||!managed||!invoke)return ReferenceDispatch::rejected;
    // IL2CPP runtime_invoke reference ABI: params[0] is the managed object,
    // never the address of the native pointer variable.
    void *args[]={managed},*exception=nullptr;
    (void)invoke(method,owner,args,&exception);
    return exception?ReferenceDispatch::exception:ReferenceDispatch::started;
}
}
