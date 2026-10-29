// Fixed, test-only settings acceptance actions. Include after housing_native.inc.
// No Unity pointer is retained across a Pump call. The original Toggle setter
// invokes the shipped PlayerPrefsToggleClient.OnValueChanged callback.
namespace nebula_settings_v1 {
enum class Target { NotificationLoginFriend, PlatformOnly };
// Mutating settings is permitted only in the reviewed test GameAssembly that
// suppresses every shipped cursor-lock/hide path.  Production helpers retain
// the read-only snapshot but fail closed before claiming the process mutex or
// invoking Unity when built for any other GameAssembly.
constexpr const char *kCursorSafeNormalGameAssemblySha256=
    "39ad8c096357f4a1e56b90524175f67b8e6cc88dcedf2c3bc0fbf87178271e3b";
constexpr const char *kCursorSafeCohortGameAssemblySha256=
    "40ce54b0b003b5d22be142787413111e105c4e26c8c25bde758c604f20b457eb";
struct ToggleObservation {
    bool scan_ok{},context_ok{},value{},manager_value{};
    unsigned key_matches{},exact_matches{};
    const char *reason="not_scanned";
};
static HANDLE single_client_mutex{};
static std::uint64_t attempts{},accepted{};

bool cursor_safe_profile() {
    return !std::strcmp(NEBULA_MOVEMENT_GAMEASSEMBLY_SHA256,
                        kCursorSafeNormalGameAssemblySha256)||
           !std::strcmp(NEBULA_MOVEMENT_GAMEASSEMBLY_SHA256,
                        kCursorSafeCohortGameAssemblySha256);
}

bool claim_single_client() {
    if(single_client_mutex)return true;
    HANDLE value=CreateMutexW(nullptr,FALSE,L"Local\\NebulaSettingsPersistenceSingleClientV1");
    if(!value)return false;
    if(GetLastError()==ERROR_ALREADY_EXISTS){CloseHandle(value);return false;}
    single_client_mutex=value;return true;
}
bool context(void *owner) {
    auto desktop=current_desktop_proof();
    if(!desktop.probe_ok||!desktop.matches_session||desktop.receives_input)return false;
    void *space=nullptr;
    return housing_base_ready(owner,space);
}
bool find_all_toggles(void *&array,std::uintptr_t &length) {
    array=nullptr;length=0;
    void *target=klass(script_image,"","PlayerPrefsToggleClient");
    const void *raw=target?api.class_type(target):nullptr;
    void *type=raw?api.type_object(raw):nullptr;
    // runtime_invoke receives managed reference parameters directly.  Only the
    // value-type Boolean argument is passed by address.
    std::uint8_t include_inactive=1;void *args[]{type,&include_inactive};
    void *method_info=method(klass(core_image,"UnityEngine","Object"),"FindObjectsOfType",2,0x1b8b0f0);
    if(!type||!invoke(method_info,nullptr,args,array)||!readable(array,0x20))return false;
    length=field<std::uintptr_t>(array,0x18);
    return length<=4096&&readable(static_cast<char*>(array)+0x20,
                                  length?length*sizeof(void*):1);
}
bool toggle_value(void *toggle,bool &value) {
    void *box=nullptr;
    return typed(toggle,"Toggle","UnityEngine.UI",true)&&
        invoke(method(klass(ui_image,"UnityEngine.UI","Toggle"),"get_isOn",0,0x1c61780),toggle,nullptr,box)&&
        boxed_bool(box,value);
}
ToggleObservation observe(void *owner,Target target,void **component_out=nullptr,void **toggle_out=nullptr) {
    ToggleObservation out{};if(component_out)*component_out=nullptr;if(toggle_out)*toggle_out=nullptr;
    out.context_ok=context(owner);if(!out.context_ok){out.reason="settings_context_guard";return out;}
    const int wanted=target==Target::NotificationLoginFriend?19:21;
    const char *wanted_name=target==Target::NotificationLoginFriend?
        "ShowNotificationLoginFriends":"Platform Only";
    void *array=nullptr;std::uintptr_t length=0;
    if(!find_all_toggles(array,length)){out.reason="settings_toggle_array_guard";return out;}
    void *match=nullptr,*match_toggle=nullptr;
    for(std::uintptr_t i=0;i<length;++i){
        void *component=field<void*>(array,0x20+i*sizeof(void*));
        if(!typed(component,"PlayerPrefsToggleClient","",true)||!readable(component,0x41))continue;
        if(field<int32_t>(component,0x28)!=wanted)continue;
        void *go=component_game_object(component);bool active=false;char name[129]{};
        if(!go||!active_hierarchy(go,active)||!active)continue;
        ++out.key_matches;
        if(!object_name(go,name,sizeof name)||std::strcmp(name,wanted_name))continue;
        void *toggle=field<void*>(component,0x38);
        if(!typed(toggle,"Toggle","UnityEngine.UI",true)||component_game_object(toggle)!=go)continue;
        ++out.exact_matches;match=component;match_toggle=toggle;
    }
    if(out.key_matches!=1||out.exact_matches!=1){out.reason="settings_toggle_identity_guard";return out;}
    void *manager=field<void*>(owner,0x168);
    if(!typed(manager,"PlayerPrefsManager")||!readable(manager,0x65)){
        out.reason="settings_manager_guard";return out;
    }
    if(!toggle_value(match_toggle,out.value)){out.reason="settings_toggle_value_guard";return out;}
    out.manager_value=field<uint8_t>(manager,target==Target::NotificationLoginFriend?0x64:0x20)!=0;
    if(out.value!=out.manager_value){out.reason="settings_value_mismatch";return out;}
    out.scan_ok=true;out.reason="ready";if(component_out)*component_out=match;if(toggle_out)*toggle_out=match_toggle;
    return out;
}
const char *toggle(void *owner,Target target,const char *&status) {
    if(!cursor_safe_profile()){status="rejected";return "settings_cursor_profile_guard";}
    if(!claim_single_client()){status="rejected";return "settings_single_client_guard";}
    void *component=nullptr,*ui_toggle=nullptr;auto before=observe(owner,target,&component,&ui_toggle);
    if(!before.scan_ok){status="rejected";return before.reason;}
    bool desired=!before.value;void *args[]{&desired};++attempts;
    void *ignored=nullptr;
    if(!invoke(method(klass(ui_image,"UnityEngine.UI","Toggle"),"set_isOn",1,0x1c617c0),ui_toggle,args,ignored)){
        status="error";return "settings_callback_exception";
    }
    auto after=observe(owner,target);
    if(!after.scan_ok||after.value!=desired||after.manager_value!=desired){
        status="error";return "settings_callback_readback_failed";
    }
    ++accepted;status="started";
    return target==Target::NotificationLoginFriend?
        "settings_notification_callback_started":"settings_platform_callback_started";
}
void snapshot(Json &j,void *owner) {
    auto notification=observe(owner,Target::NotificationLoginFriend);
    auto platform=observe(owner,Target::PlatformOnly);
    j.append(",\"settings_acceptance\":{\"cursor_safe_profile\":");j.boolean(cursor_safe_profile());
    j.append(",\"single_client_claimed\":");j.boolean(single_client_mutex!=nullptr);
    j.append(",\"attempts\":");j.integer(attempts);j.append(",\"accepted\":");j.integer(accepted);
    j.append(",\"notification\":{\"ready\":");j.boolean(notification.scan_ok);
    j.append(",\"value\":");j.boolean(notification.value);j.append(",\"manager_value\":");j.boolean(notification.manager_value);
    j.append(",\"key_matches\":");j.integer(notification.key_matches);j.append(",\"exact_matches\":");j.integer(notification.exact_matches);
    j.append(",\"reason\":");j.string(notification.reason);j.append("}");
    j.append(",\"platform\":{\"ready\":");j.boolean(platform.scan_ok);
    j.append(",\"value\":");j.boolean(platform.value);j.append(",\"manager_value\":");j.boolean(platform.manager_value);
    j.append(",\"key_matches\":");j.integer(platform.key_matches);j.append(",\"exact_matches\":");j.integer(platform.exact_matches);
    j.append(",\"reason\":");j.string(platform.reason);j.append("}}");
}
}
