#pragma once
#include <cstring>
#include "automation_wardrobe.h"

// Pure policy boundary for the authored preset-menu/tile callbacks. Runtime
// discovery remains in automation.cpp and retains no Unity object.
namespace nac {
inline bool preset_list_layout_valid(int count,int capacity,bool element_span_readable) {
    return count>=0&&count<=256&&capacity>=count&&capacity<=65536&&
           (count==0||element_span_readable);
}
struct PresetState {
    bool scene_editor{},current_owner{},session_ready{},alive{},initialized{},controller_ready{},preset_manager_ready{};
    bool cloud_ready{},event_system_ready{},load_menu_ready{},loading_circle_ready{},loading_preset_ready{};
    bool menu_active{},loading_active{},tiles_probe_ok{};
    unsigned matches{};
};
inline const char *preset_reason(const PresetState &s) {
    if(!s.scene_editor)return "scene_not_character_editor";
    if(!s.current_owner)return "ps4info_not_current";
    if(!s.session_ready)return "editor_session_not_ready";
    if(!s.alive)return "editor_unavailable";
    if(!s.initialized)return "editor_not_initialized";
    if(!s.controller_ready)return "editor_controller_unavailable";
    if(!s.preset_manager_ready)return "preset_manager_unavailable";
    if(!s.cloud_ready)return "preset_cloud_unavailable";
    if(!s.event_system_ready)return "preset_event_system_unavailable";
    if(!s.load_menu_ready)return "preset_menu_unavailable";
    if(!s.loading_circle_ready)return "preset_loading_circle_unavailable";
    if(!s.loading_preset_ready)return "preset_loading_object_unavailable";
    if(!s.tiles_probe_ok)return "preset_tiles_probe_unavailable";
    if(s.matches>1)return "preset_tile_ambiguous";
    return "ready";
}
enum class PresetPlan { Rejected, DispatchTile, OpenAndWait, WaitExisting };
inline PresetPlan preset_plan(const PresetState &s) {
    if(std::strcmp(preset_reason(s),"ready"))return PresetPlan::Rejected;
    if(s.loading_active)return PresetPlan::Rejected;
    if(!s.menu_active)return PresetPlan::OpenAndWait;
    return s.matches==1?PresetPlan::DispatchTile:PresetPlan::WaitExisting;
}
enum class PresetDispatch { Rejected, Started, Exception };
inline PresetDispatch dispatch_preset_text(const PresetState &s,const void *method,void *owner,void *text,Invoke invoke) {
    if(preset_plan(s)!=PresetPlan::DispatchTile||!method||!owner||!text||!invoke)return PresetDispatch::Rejected;
    // IL2CPP reference parameters are the managed object itself. Only value
    // types use the address of native storage in runtime_invoke's args array.
    void *args[]={text},*exception=nullptr;
    (void)invoke(method,owner,args,&exception);
    return exception?PresetDispatch::Exception:PresetDispatch::Started;
}
}
