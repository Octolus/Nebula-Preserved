// Included after housing_wiring.inc, before add_snapshot. Main-thread only.
// Fixed reviewed HAT acceptance target. No address argument or network writes.
namespace character_exit {
unsigned phase{},requests{};uint64_t deadline{};char digest[65]{};
int menu_instance{};const char* code="idle";
bool pending(){return phase==1||phase==2;}
void fail(const char* reason){phase=0;code=reason;menu_instance=0;}
bool instance_id(void* object,int& value){
    value=0;void* boxed=nullptr;void* get_id=method(klass(core_image,"UnityEngine","Object"),"GetInstanceID",0,0x1b8b190);
    return invoke(get_id,object,nullptr,boxed)&&boxed_int(boxed,value)&&value!=0;
}
bool context(void* owner,void*& menu,const char*& reason){
    auto desktop=current_desktop_proof();char fresh[65]{},scene[128]{};
    if(GetCurrentThreadId()!=thread||!initialized||disabled||
       !desktop.probe_ok||!desktop.matches_session||desktop.receives_input||
       !typed(owner,"PS4Info","",true)||singleton(api.object_class(owner),"_singleton")!=owner||
       !session_digest(owner,fresh)||!nac::same_digest(digest,fresh)||
       !active_scene(scene,sizeof scene)||std::strcmp(scene,"CharacterEditor")){
        reason="character_exit_session_or_desktop_guard";return false;}
    menu=singleton(klass(script_image,"","CE_Menu"),"_singleton");
    if(!typed(menu,"CE_Menu","",true)||!readable(menu,0x329)||
       !field<uint8_t>(menu,0x328)||!field<uint8_t>(menu,0x2a8)||
       field<uint32_t>(menu,0x78)!=1||!housing_text_is(field<void*>(menu,0xc8),"CharNoHatV1")){
        reason="character_exit_saved_editor_guard";return false;}
    int current=0;if(!instance_id(menu,current)||(menu_instance&&current!=menu_instance)){
        reason="character_exit_menu_generation_guard";return false;}
    return true;
}
const char* start(void* owner,uint64_t until,const char*& status){
    status="rejected";
    if(requests>=2||pending())return "character_exit_request_limit_or_pending";
    if(preset_pending||remove_pending||save_pending||store_phase_pending()||
       movement_pending()||economy_pending()||social_pending()||nebula_public_chat_v2::pending()||
       housing_pending()||resource_ui_core::pending()||resource_navigation_core::pending()||additional_module_pending())return "character_exit_overlap";
    bool saved=save_completion_observed&&save_seen_active&&!std::strcmp(save_target,"CharNoHatV1");
    bool loaded=!preset_pending&&!std::strcmp(preset_last_code,"preset_load_completed")&&!std::strcmp(preset_target,"CharNoHatV1");
    if(!saved&&!loaded)return "character_exit_original_save_or_load_not_observed";
    if(!session_digest(owner,digest))return "character_exit_session_unavailable";
    void* menu=nullptr;const char* reason=nullptr;if(!context(owner,menu,reason))return reason;
    void* window=field<void*>(menu,0x1c8);void* button=field<void*>(menu,0x210);
    bool active=false;void* component_button=nullptr;char name[65]{};
    if(!typed(window,"GameObject","UnityEngine",true)||!active_hierarchy(window,active)||active||
       !object_name(button,name,sizeof name)||std::strcmp(name,"BTNMENU_Exit")||
       !button_ready(button,component_button,reason))return "character_exit_original_button_guard";
    void* stack=field<void*>(menu,0x2a0);void* stack_list=field<void*>(stack,0x10);
    void* event=field<void*>(menu,0x58);void* editor=singleton(klass(script_image,"","MANAGEREditor"),"_singleton");
    if(!typed(stack,"CE_StackMenus","",false)||!typed(stack_list,"List`1","System.Collections.Generic")||
       !readable(stack_list,0x20)||field<int>(stack_list,0x18)!=0||
       !typed(event,"EventSystem","UnityEngine.EventSystems",true)||!typed(editor,"MANAGEREditor","",true)||
       !typed(field<void*>(editor,0x178),"NETGcloudEditor","",false))return "character_exit_root_menu_or_receiver_guard";
    // Invoke the exact original handler on the current menu, with its own
    // serialized exit button. Original body opens WindowExit and pushes stack.
    void* method_exit=method(klass(script_image,"","CE_Menu"),"onClickExit",1,0x48fa40);
    void* ignored=nullptr;void* args[]={button};
    if(!instance_id(menu,menu_instance)){status="error";return "character_exit_menu_generation_guard";}
    if(!invoke(method_exit,menu,args,ignored)){menu_instance=0;status="error";return "character_exit_open_callback_exception";}
    if(!active_hierarchy(window,active)||!active){menu_instance=0;status="error";return "character_exit_confirmation_not_opened";}
    deadline=until;++requests;phase=1;code="character_exit_confirmation_opened";status="started";return code;
}
void pump(void* owner,uint64_t now){
    if(!pending())return;
    if(now>deadline){fail("character_exit_completion_timeout");return;}
    if(phase==2){
        auto desktop=current_desktop_proof();char fresh[65]{};void* manager=nullptr;
        if(!desktop.probe_ok||!desktop.matches_session||desktop.receives_input||
           !session_digest(owner,fresh)||!nac::same_digest(digest,fresh)){fail("character_exit_session_lost");return;}
        char scene[128]{};
        if(active_scene(scene,sizeof scene)&&!std::strcmp(scene,"Nexus")&&housing_base_ready(owner,manager)){
            phase=3;code="character_exit_world_ready";menu_instance=0;
        }
        return;
    }
    void* menu=nullptr;const char* reason=nullptr;if(!context(owner,menu,reason)){fail(reason);return;}
    bool active=false;void* window=field<void*>(menu,0x1c8);
    if(!active_hierarchy(window,active)||!active){fail("character_exit_confirmation_lost");return;}
    // Original body indexes CE_StackMenus.stack[0], then restores selection,
    // clears stack, disables EventSystem and invokes save+exit coroutine.
    void* stack=field<void*>(menu,0x2a0);void* list=field<void*>(stack,0x10);
    if(!typed(stack,"CE_StackMenus","",false)||!typed(list,"List`1","System.Collections.Generic")||
       !readable(list,0x20)||field<int>(list,0x18)<1||field<int>(list,0x18)>32){fail("character_exit_menu_stack_guard");return;}
    void* entries=field<void*>(list,0x10);
    if(!readable(entries,0x28)||field<uintptr_t>(entries,0x18)<1||field<void*>(entries,0x20)!=field<void*>(menu,0x210)){
        fail("character_exit_stack_button_mismatch");return;}
    void* event=field<void*>(menu,0x58);void* editor=singleton(klass(script_image,"","MANAGEREditor"),"_singleton");
    if(!typed(event,"EventSystem","UnityEngine.EventSystems",true)||!typed(editor,"MANAGEREditor","",true)||
       !typed(field<void*>(editor,0x178),"NETGcloudEditor","",false)){fail("character_exit_original_receiver_guard");return;}
    void* original=method(klass(script_image,"","CE_Menu"),"onClickSaveChanges",0,0x490300);void* ignored=nullptr;
    if(!invoke(original,menu,nullptr,ignored)){fail("character_exit_save_callback_exception");return;}
    phase=2;code="character_exit_original_save_callback_started";
}
void json(Json& j){
    j.append(",\"character_exit\":{\"phase\":");j.integer(phase);
    j.append(",\"pending\":");j.boolean(pending());j.append(",\"code\":");j.string(code);j.append("}");
}
}
