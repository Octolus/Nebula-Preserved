// Read-only failure decomposition. Existing SettingsOpen dispatch is unchanged.
// No raw pointers, names, GUIDs or process values are emitted. No action is added.
namespace nebula_settings_open_diagnostic_v2 {
struct Observation {
    bool context{},array_ok{},layout_ok{},owned_manager_typed{},side_go_typed{};
    bool side_active_probe{},side_active{},side_state{},root_panel_probe{},root_panel_active{};
    unsigned array_length{},typed_count{},root_reference_matches{},panel_name_matches{};
    unsigned controls_name_matches{},button_name_matches{},button_active_probes{};
    unsigned button_active_matches{},button_component_matches{},complete_matches{};
    const char* original_reason="context_unproven";
};
Observation observe(void* owner) {
    Observation out{};void* space=nullptr;
    if(!nebula_settings_v1::context(owner)||!housing_base_ready(owner,space))return out;
    out.context=true;
    auto original=nebula_settings_open_v1::observe(owner);out.original_reason=original.reason;
    void* owned=field<void*>(space,0x220);out.owned_manager_typed=typed(owned,"OptionsManager","",true);
    void* side=field<void*>(space,0x1e0);out.side_go_typed=typed(side,"GameObject","UnityEngine",true);
    out.side_state=field<uint8_t>(space,0x1d8)!=0;
    if(out.side_go_typed)out.side_active_probe=active_hierarchy(side,out.side_active);
    if(out.owned_manager_typed)out.root_panel_probe=active_hierarchy(component_game_object(owned),out.root_panel_active);
    void* target=klass(script_image,"","OptionsManager");const void* raw=target?api.class_type(target):nullptr;
    void* type=raw?api.type_object(raw):nullptr;void* array=nullptr;uint8_t inactive=1;void* args[]{type,&inactive};
    if(!type||!invoke(method(klass(core_image,"UnityEngine","Object"),"FindObjectsOfType",2,0x1b8b0f0),nullptr,args,array)||!readable(array,0x20))return out;
    out.array_ok=true;
    const auto length=field<uintptr_t>(array,0x18);
    if(length>128||!readable(static_cast<char*>(array)+0x20,length?length*sizeof(void*):1))return out;
    out.layout_ok=true;out.array_length=static_cast<unsigned>(length);
    for(uintptr_t i=0;i<length;++i) {
        void* manager=field<void*>(array,0x20+i*sizeof(void*));
        if(!typed(manager,"OptionsManager","",true)||!readable(manager,0xb9))continue;
        ++out.typed_count;if(manager==owned)++out.root_reference_matches;
        void* panel=component_game_object(manager);void* controls=field<void*>(manager,0x18);
        void* button=field<void*>(manager,0x20);bool button_active=false;
        const bool panel_match=nebula_settings_open_v1::named(panel,"UIOptions");
        const bool controls_match=nebula_settings_open_v1::named(controls,"ControlsWindow");
        const bool button_match=nebula_settings_open_v1::named(button,"BTN_Settings");
        const bool active_probe=active_hierarchy(button,button_active);
        const bool component_match=typed(component(button,ui_image,"UnityEngine.UI","Button"),"Button","UnityEngine.UI",true);
        out.panel_name_matches+=panel_match;out.controls_name_matches+=controls_match;
        out.button_name_matches+=button_match;out.button_active_probes+=active_probe;
        out.button_active_matches+=active_probe&&button_active;
        out.button_component_matches+=component_match;
        out.complete_matches+=panel_match&&controls_match&&button_match&&active_probe&&button_active&&component_match;
    }
    return out;
}
void snapshot(Json& j,void* owner) {
    auto value=observe(owner);j.append(",\"settings_open_diagnostic_v2\":{");
#define SETTINGS_DIAG_BOOL(key) j.append("\"" #key "\":");j.boolean(value.key);j.append(",")
    SETTINGS_DIAG_BOOL(context);SETTINGS_DIAG_BOOL(array_ok);SETTINGS_DIAG_BOOL(layout_ok);
    SETTINGS_DIAG_BOOL(owned_manager_typed);SETTINGS_DIAG_BOOL(side_go_typed);
    SETTINGS_DIAG_BOOL(side_active_probe);SETTINGS_DIAG_BOOL(side_active);SETTINGS_DIAG_BOOL(side_state);
    SETTINGS_DIAG_BOOL(root_panel_probe);SETTINGS_DIAG_BOOL(root_panel_active);
#undef SETTINGS_DIAG_BOOL
#define SETTINGS_DIAG_COUNT(key) j.append("\"" #key "\":");j.integer(value.key);j.append(",")
    SETTINGS_DIAG_COUNT(array_length);SETTINGS_DIAG_COUNT(typed_count);SETTINGS_DIAG_COUNT(root_reference_matches);
    SETTINGS_DIAG_COUNT(panel_name_matches);SETTINGS_DIAG_COUNT(controls_name_matches);SETTINGS_DIAG_COUNT(button_name_matches);
    SETTINGS_DIAG_COUNT(button_active_probes);SETTINGS_DIAG_COUNT(button_active_matches);
    SETTINGS_DIAG_COUNT(button_component_matches);SETTINGS_DIAG_COUNT(complete_matches);
#undef SETTINGS_DIAG_COUNT
    j.append("\"original_reason\":");j.string(value.original_reason);j.append("}");
}
}
