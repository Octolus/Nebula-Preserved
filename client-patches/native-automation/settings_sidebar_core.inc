// Original sidebar -> unchanged original settings opener. No raw field writes.
// Included after settings_native_core.inc and settings_open_core.inc.
namespace nebula_settings_sidebar_v1 {
namespace policy=nebula_settings_sidebar_policy;
bool instance_id(void*value,int&id) {
    void*box=nullptr;id=0;
    return value&&invoke(method(klass(core_image,"UnityEngine","Object"),"GetInstanceID",0,0x1b8b190),value,nullptr,box)&&
        boxed_int(box,id)&&id!=0;
}
bool active_self(void*go,bool&active) {
    void*box=nullptr;return typed(go,"GameObject","UnityEngine",true)&&
      invoke(method(klass(core_image,"UnityEngine","GameObject"),"get_activeSelf",0,0x1b87b30),go,nullptr,box)&&boxed_bool(box,active);
}
bool child_of(void*child,void*parent) {
    void*child_transform=nullptr;void*parent_transform=nullptr;void*box=nullptr;bool result=false;
    auto get=method(klass(core_image,"UnityEngine","GameObject"),"get_transform",0,0x1b87c50);
    if(!typed(child,"GameObject","UnityEngine",true)||!typed(parent,"GameObject","UnityEngine",true)||
       !invoke(get,child,nullptr,child_transform)||!invoke(get,parent,nullptr,parent_transform)||
       !derived_unity(child_transform,"Transform","UnityEngine")||
       !derived_unity(parent_transform,"Transform","UnityEngine"))return false;
    void*args[]{parent_transform};
    return invoke(method(klass(core_image,"UnityEngine","Transform"),"IsChildOf",1,0x1b97550),child_transform,args,box)&&
      boxed_bool(box,result)&&result;
}
struct Adapter final:policy::Host {
    void*owner;void*side_input{};
    explicit Adapter(void*value):owner(value){}
    bool capture(policy::Observation&out,const char*&reason) noexcept override {
        out={};side_input=nullptr;void*space=nullptr;reason="settings_sidebar_context_guard";
        if(!nebula_settings_v1::context(owner)||!housing_base_ready(owner,space))return false;
        void*options=field<void*>(space,0x220);void*sidebar=field<void*>(space,0x1e0);
        reason="settings_sidebar_owned_options_guard";
        if(!typed(options,"OptionsManager","",true)||!readable(options,0xb9)||
           !typed(sidebar,"GameObject","UnityEngine",true))return false;
        void*panel=component_game_object(options);void*controls=field<void*>(options,0x18);void*button=field<void*>(options,0x20);
        reason="settings_sidebar_authored_identity_guard";
        void*button_component=component(button,ui_image,"UnityEngine.UI","Button");
        if(!nebula_settings_open_v1::named(panel,"UIOptions")||!nebula_settings_open_v1::named(controls,"ControlsWindow")||
           !nebula_settings_open_v1::named(button,"BTN_Settings")||
           !typed(button_component,"Button","UnityEngine.UI",true)||component_game_object(button_component)!=button||
           !child_of(button,sidebar))return false;
        bool self=false,side_active=false,button_active=false,panel_active=false;
        reason="settings_sidebar_active_state_probe_guard";
        if(!active_self(button,self)||!self||!active_hierarchy(sidebar,side_active)||
           !active_hierarchy(button,button_active)||!active_hierarchy(panel,panel_active))return false;
        const bool options_open=field<uint8_t>(options,0xb8)!=0;
        if(panel_active!=options_open){reason="settings_sidebar_panel_state_guard";return false;}
        void*memory=field<void*>(space,0x2c0);void*info=field<void*>(memory,0x10);void*player=field<void*>(info,0x30);
        void*input=field<void*>(player,0x60);void*control=field<void*>(player,0x28);
        side_input=field<void*>(player,0x80);
        reason="settings_sidebar_owned_input_guard";
        if(!typed(input,"NebulaInput","Assets.Scripts.NebulaPlayers",true)||!readable(input,0x54)||
           !typed(control,"NebulaPlayerControl","Assets.Scripts.NebulaPlayers",true)||!readable(control,0x40)||
           !typed(side_input,"NebulaInputSideMenu","Assets.Scripts.NebulaPlayers",true)||!readable(side_input,0x29)||
           field<void*>(input,0x28)!=control||field<void*>(control,0x30)!=player||field<void*>(input,0x48)!=side_input||
           !field<uint8_t>(input,0x18)||!field<uint8_t>(side_input,0x18))return false;
        void*pad=field<void*>(side_input,0x20);
        if(!typed(pad,"PadPS4")||pad!=field<void*>(control,0x38)||
           pad!=singleton(klass(script_image,"","PadPS4"),"padPS4"))return false;
        reason="settings_sidebar_primitive_binding_guard";
        if(!session_digest(owner,out.binding.session)||!instance_id(space,out.binding.manager)||
           !instance_id(options,out.binding.options)||!instance_id(sidebar,out.binding.sidebar)||
           !instance_id(side_input,out.binding.input))return false;
        auto original=nebula_settings_open_v1::observe(owner);
        out.original_ready=original.ready&&original.manager==options;
        out.original_open=options_open;out.button_active=button_active;
        const bool side_state=field<uint8_t>(space,0x1d8)!=0;
        out.sidebar_open=side_state&&side_active;
        void*chat=field<void*>(space,0x150);
        const bool input_allowed=field<uint8_t>(side_input,0x28)&&
          !field<uint8_t>(space,0xf0)&&!field<uint8_t>(space,0x26f)&&!field<uint8_t>(space,0x270)&&
          !field<uint8_t>(space,0x1dc)&&!field<uint8_t>(space,0x271)&&!field<uint8_t>(space,0x1d9)&&
          typed(chat,"Chat","",true)&&readable(chat,0xe1)&&!field<uint8_t>(chat,0xe0)&&!field<uint8_t>(chat,0xc0);
        out.eligible_closed=!original.ready&&!std::strcmp(original.reason,"settings_open_identity_guard")&&
          !options_open&&!side_state&&!side_active&&!button_active&&input_allowed;
        reason="ready";return true;
    }
    bool open_sidebar() noexcept override {
        void*ignored=nullptr;
        return side_input&&invoke(method(klass(script_image,"Assets.Scripts.NebulaPlayers","NebulaInputSideMenu"),
          "OpenSideMenu",0,0x5f1430),side_input,nullptr,ignored);
    }
    policy::Result open_original_settings() noexcept override {
        const char*status=nullptr;auto code=nebula_settings_open_v1::open(owner,status);
        return {status,code};
    }
};
const char*open(void*owner,const char*&status) {
    Adapter host(owner);const auto result=policy::run(host);status=result.status;return result.code;
}
}
