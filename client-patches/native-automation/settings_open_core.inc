// Original, fixed OptionsManager.OnClick settings-panel opener. No raw state writes.
namespace nebula_settings_open_v1 {
struct Observation { bool ready{},open{},button_active{};unsigned manager_matches{};const char *reason="not_scanned";void *manager{}; };
bool named(void *object,const char *expected) { char value[129]{};return object&&object_name(object,value,sizeof value)&&!std::strcmp(value,expected); }
Observation observe(void *owner) {
    Observation out{};void *space=nullptr;
    if(!housing_base_ready(owner,space)){out.reason="settings_open_context_guard";return out;}
    void *target=klass(script_image,"","OptionsManager");const void *raw=target?api.class_type(target):nullptr;
    void *type=raw?api.type_object(raw):nullptr,*array=nullptr;std::uint8_t include_inactive=1;
    void *args[]{type,&include_inactive};
    if(!type||!invoke(method(klass(core_image,"UnityEngine","Object"),"FindObjectsOfType",2,0x1b8b0f0),nullptr,args,array)||!readable(array,0x20)){
        out.reason="settings_open_manager_array_guard";return out;
    }
    auto length=field<std::uintptr_t>(array,0x18);
    if(length>128||!readable(static_cast<char*>(array)+0x20,length?length*sizeof(void*):1)){
        out.reason="settings_open_manager_array_layout";return out;
    }
    for(std::uintptr_t i=0;i<length;++i){
        void *manager=field<void*>(array,0x20+i*sizeof(void*));
        if(!typed(manager,"OptionsManager")||!readable(manager,0xb9))continue;
        void *panel=component_game_object(manager),*controls=field<void*>(manager,0x18),*button=field<void*>(manager,0x20);
        bool button_active=false;
        if(!named(panel,"UIOptions")||!named(controls,"ControlsWindow")||!named(button,"BTN_Settings")||
           !active_hierarchy(button,button_active)||!button_active||
           !typed(component(button,ui_image,"UnityEngine.UI","Button"),"Button","UnityEngine.UI",true))continue;
        ++out.manager_matches;out.manager=manager;out.open=field<std::uint8_t>(manager,0xb8)!=0;out.button_active=button_active;
    }
    if(out.manager_matches!=1){out.reason="settings_open_identity_guard";return out;}
    bool panel_active=false;
    if(!active_hierarchy(component_game_object(out.manager),panel_active)){out.reason="settings_open_panel_probe";return out;}
    if(panel_active!=out.open){out.reason="settings_open_state_mismatch";return out;}
    out.ready=true;out.reason="ready";return out;
}
const char *open(void *owner,const char *&status) {
    auto before=observe(owner);if(!before.ready){status="rejected";return before.reason;}
    if(before.open){status="ok";return "settings_panel_already_open";}
    void *ignored=nullptr;
    if(!invoke(method(klass(script_image,"","OptionsManager"),"OnClick",0,0x481b10),before.manager,nullptr,ignored)){
        status="error";return "settings_open_callback_exception";
    }
    auto after=observe(owner);
    if(!after.ready||!after.open){status="error";return "settings_open_callback_readback_failed";}
    status="started";return "settings_open_callback_started";
}
}
