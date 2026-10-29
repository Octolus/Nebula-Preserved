// Include after automation.cpp shared IL2CPP helpers and before add_snapshot/publish.
namespace resource_ui_core {
namespace nru=nebula_resource_ui;
namespace nrs=nebula_resource_selection;
constexpr const char*kCompanion="A0IQgRXmw2UMG8T5UGrVE022o7Id25GU";
constexpr const char*kLocomotion="AJ7C1vNaTXDE2G5xRD5Uq4Tqv22a775K";
std::uint64_t hash_text(const char*s){std::uint64_t h=1469598103934665603ull;for(;s&&*s;++s){h^=std::uint8_t(*s);h*=1099511628211ull;}return h;}
bool binding_same_base(const nru::Binding&a,const nru::Binding&b){return a.session_hash==b.session_hash&&a.local_guid_hash==b.local_guid_hash&&a.scene_hash==b.scene_hash&&a.local_net_id==b.local_net_id&&a.manager_instance_id==b.manager_instance_id;}

struct Tracker {
  nru::Binding last_binding{};
  std::uint64_t epoch{},comp_sig{},loco_sig{},comp_gen{},loco_gen{};
  bool binding_init{},comp_init{},loco_init{};
};
struct Adapter final:nru::Host {
  void*owner{};Tracker&tracker;
  Adapter(void*o,Tracker&t):owner(o),tracker(t){}
  bool bind(void*manager,void*local,nru::Binding&out,const char*&reason){
    char digest[65]{},guid[257]{},info_guid[257]{},player_guid[257]{},scene[128]{};out={};
    void*memory=field<void*>(manager,0x2c0);void*info=memory?field<void*>(memory,0x10):nullptr;
    void*player=info?field<void*>(info,0x30):nullptr;
    if(singleton(api.object_class(owner),"_singleton")!=owner||!session_digest(owner,digest)||
       !managed_string(field<void*>(owner,0xe8),guid,sizeof guid)||!guid[0]||
       !active_scene(scene,sizeof scene)||!scene[0]||!typed(local,"NetworkIdentity","Mirror",true)){
      SecureZeroMemory(digest,sizeof digest);SecureZeroMemory(guid,sizeof guid);reason="resource_binding_guard";return false;}
    if(!field<std::uint8_t>(local,0x1a)||!field<std::uint8_t>(local,0x1b)||
       !typed(memory,"Memory","Assets.Scripts.Memories")||
       !typed(info,"PlayerInfo","Assets.Scripts.Memories")||
       !typed(player,"NebulaPlayer","",true)||!field<std::uint8_t>(player,0x9c)||
       field<void*>(player,0xf8)!=local||
       !managed_string(field<void*>(info,0x18),info_guid,sizeof info_guid)||!info_guid[0]||
       !managed_string(field<void*>(player,0xa0),player_guid,sizeof player_guid)||!player_guid[0]||
       std::strcmp(guid,info_guid)||std::strcmp(guid,player_guid)){
      SecureZeroMemory(digest,sizeof digest);SecureZeroMemory(guid,sizeof guid);
      SecureZeroMemory(info_guid,sizeof info_guid);SecureZeroMemory(player_guid,sizeof player_guid);
      reason="resource_owned_identity_guard";return false;}
    std::uint32_t player_info_net_id=0;if(!resource_player_info_net_id_exact(info,local,player_info_net_id)){reason="resource_player_info_netid_guard";return false;}
    void*box=nullptr;void*m=method(api.object_class(manager),"GetInstanceID",0,0x1b8b190);int id=0;
    if(!::invoke(m,manager,nullptr,box)||!boxed_int(box,id)||!id){
      SecureZeroMemory(digest,sizeof digest);SecureZeroMemory(guid,sizeof guid);
      SecureZeroMemory(info_guid,sizeof info_guid);SecureZeroMemory(player_guid,sizeof player_guid);
      reason="resource_manager_incarnation_guard";return false;}
    out.session_hash=hash_text(digest);out.local_guid_hash=hash_text(guid);out.scene_hash=hash_text(scene);
    out.local_net_id=field<std::uint32_t>(local,0x28);out.manager_instance_id=id;out.valid=out.session_hash&&out.local_guid_hash&&out.scene_hash&&out.local_net_id;
    SecureZeroMemory(digest,sizeof digest);SecureZeroMemory(guid,sizeof guid);
    SecureZeroMemory(info_guid,sizeof info_guid);SecureZeroMemory(player_guid,sizeof player_guid);
    if(!tracker.binding_init||!binding_same_base(tracker.last_binding,out)){tracker.last_binding=out;tracker.binding_init=true;++tracker.epoch;tracker.comp_init=tracker.loco_init=false;tracker.comp_gen=tracker.loco_gen=0;}
    out.generation_epoch=tracker.epoch;return out.valid;
  }
  bool capture(nru::Action action,bool require_selection,nru::Observation&ob,nrs::Snapshot&s,const char*&reason) noexcept override {
    ob={};s={};void*local=nullptr;auto network=observe_network(local);void*manager=singleton(klass(script_image,"","ManagerInstance"),"_singleton");
    auto desktop=current_desktop_proof();char scene_name[128]{};
    if(!derived_unity(manager,"ManagerInstance")||field<std::uint8_t>(manager,0x122)||
       std::strcmp(nac::network_reason(network),"ready")||!bind(manager,local,ob.binding,reason)){reason=reason?reason:"resource_context_guard";return false;}
    const bool companion=action==nru::Action::SelectCompanion||action==nru::Action::RemoveCompanion;
    const bool removing=action==nru::Action::RemoveCompanion||action==nru::Action::RemoveLocomotion;
    const char*wheel_type=companion?"MenuWheelPets":"MenuWheelLocomotions";const char*row_type=companion?"PetPrefab":"LocomotionPrefab";const char*fixture=companion?kCompanion:kLocomotion;
    void*persist=field<void*>(owner,0x240);if(!typed(persist,"Persistency","Assets.Scripts.Memories",true)){reason="resource_persistency_guard";return false;}
    char current[65]{};void*current_managed=field<void*>(persist,companion?0x18:0x20);if(current_managed&&!managed_string(current_managed,current,sizeof current)){reason="resource_current_value_guard";return false;}
    ob.current_empty=!current[0];ob.current_exact=!std::strcmp(current,fixture);std::uint64_t sig=hash_text(current);auto&prior=companion?tracker.comp_sig:tracker.loco_sig;auto&gen=companion?tracker.comp_gen:tracker.loco_gen;auto&init=companion?tracker.comp_init:tracker.loco_init;if(!init){prior=sig;init=true;}else if(prior!=sig){prior=sig;++gen;}ob.resource_generation=gen;
    if(!require_selection){reason="ready";return true;}
    void*menu=field<void*>(manager,0x1c8);void*wheel=menu?field<void*>(menu,companion?0x90:0x98):nullptr;
    bool wheel_active=false;s.main_thread=GetCurrentThreadId()==thread;
    s.exact_profile=desktop.probe_ok&&desktop.matches_session&&!desktop.receives_input;
    s.authenticated=field<std::uint8_t>(owner,0xfa)!=0;
    s.same_session=ob.binding.valid;s.world_scene=active_scene(scene_name,sizeof scene_name)&&scene_name[0]&&
      std::strcmp(scene_name,"Login")&&std::strcmp(scene_name,"Initial");
    s.local_player=local!=nullptr;s.owned_identity=ob.binding.valid;
    s.network_ready=network.connection_ready;s.travelling=false;s.other_action_pending=false;
    s.exact_wheel=typed(wheel,wheel_type,"",true);s.wheel_visible=s.exact_wheel&&active_hierarchy(component_game_object(wheel),wheel_active)&&wheel_active&&field<std::uint8_t>(manager,0x1d9);
    int count=0;void**buttons=nullptr;const char*failure=nullptr;if(!s.wheel_visible||!list_items(field<void*>(wheel,0x90),count,buttons,failure)||count<1||count>256){reason=failure?failure:"resource_wheel_rows_guard";return false;}
    void*selected=nullptr,*selected_method=method(klass(ui_image,"UnityEngine.EventSystems","EventSystem"),"get_currentSelectedGameObject",0,0x4f14f0);
    void*event_system=field<void*>(menu,0x78);
    if(!typed(event_system,"EventSystem","UnityEngine.EventSystems",true)||
       !::invoke(selected_method,event_system,nullptr,selected)||
       (selected&&!typed(selected,"GameObject","UnityEngine",true))){reason="resource_event_selection_guard";return false;}
    unsigned compatible=0;void*receiver=nullptr;void*selected_button=nullptr;
    for(int i=0;i<count;++i){void*button=buttons[i];if(!typed(button,"Button","UnityEngine.UI",true)){reason="resource_button_list_guard";return false;}void*object=component_game_object(button);void*row=component(object,script_image,"",row_type);if(!typed(row,row_type,"",false)){reason="resource_row_class_guard";return false;}bool empty=field<std::uint8_t>(row,0x28)!=0;char row_id[65]{};bool id_ok=empty||managed_string(field<void*>(row,0x30),row_id,sizeof row_id);bool exact=id_ok&&(empty?removing:!std::strcmp(row_id,fixture));if(!exact)continue;if(object==selected){++compatible;receiver=row;selected_button=object;s.empty_row=empty;}}
    s.one_selected_row=compatible==1;s.receiver_real_class=receiver&&typed(receiver,row_type,"",false);s.receiver_live=receiver&&readable(receiver,0x38);s.row_active=false;s.button_interactable=false;void*button_component=nullptr;
    if(selected_button){bool active=false;s.row_active=active_hierarchy(selected_button,active)&&active;const char*button_reason=nullptr;s.button_interactable=button_ready(selected_button,button_component,button_reason);}
    bool entitled=false;if(!removing){int purchase_type=companion?3:1;void*owned=nullptr,*args[1]{&purchase_type};
      void*get_ids=method(api.object_class(persist),"GetIdAssets",1,0x6164c0);if(!::invoke(get_ids,persist,args,owned)){reason="resource_entitlement_invoke_guard";return false;}
      int owned_count=0;void**owned_items=nullptr;if(!list_items(owned,owned_count,owned_items,failure)||owned_count<0||owned_count>4096){reason=failure?failure:"resource_entitlement_list_guard";return false;}
      unsigned exact_owned=0;for(int i=0;i<owned_count;++i){char id[65]{};if(!managed_string(owned_items[i],id,sizeof id)){reason="resource_entitlement_id_guard";return false;}if(!std::strcmp(id,fixture))++exact_owned;}entitled=exact_owned==1;}
    s.entitlement_current=removing?false:entitled;s.exact_resource_id=compatible==1;s.requested_remove=removing;s.receiver=receiver;
    reason="ready";return true;
  }
  nrs::Result invoke(nru::Action action,const nrs::Snapshot&s,const char*&reason) noexcept override {
    nrs::Api bridge{};bridge.pinned_method=[](const char*cl,const char*name,std::uint32_t rva)->void*{return method(klass(script_image,"",cl),name,0,rva);};
    bridge.runtime_invoke=[](void*m,void*r,void**a,void**e)->void*{return api.invoke(m,r,a,e);};
    auto kind=(action==nru::Action::SelectCompanion||action==nru::Action::RemoveCompanion)?nrs::Kind::companion:nrs::Kind::locomotion;
    auto result=nrs::dispatch(kind,s,bridge);reason=result==nrs::Result::dispatched?"resource_callback_started":result==nrs::Result::exception?"resource_managed_exception":"resource_callback_guard";return result;
  }
};
nru::Module module;Tracker tracker{};const char*last_code="resource_idle";
bool pending(){return module.pending();}
// The owner and Adapter are frame-local. Module retains only immutable scalar
// operation binding/generation values; no managed pointer crosses a pump.
const char*dispatch(void*owner,nru::Action action,std::uint64_t now,std::uint64_t deadline,const char*&status){if(!module.pending())module.reset();Adapter current(owner,tracker);auto r=module.begin(current,action,now,deadline);last_code=r.code;status=r.phase==nru::Phase::Awaiting?"started":"rejected";return last_code;}
void pump(void*owner,std::uint64_t now){if(!module.pending())return;Adapter current(owner,tracker);auto r=module.poll(current,now);last_code=r.code;}
void snapshot(Json&j,void*owner){Tracker probe_tracker{};Adapter probe(owner,probe_tracker);nru::Observation o{};nrs::Snapshot s{};const char*reason=nullptr;bool companion=probe.capture(nru::Action::SelectCompanion,false,o,s,reason);j.append(",\"resource_ui\":{\"pending\":");j.boolean(pending());j.append(",\"last_code\":");j.string(last_code);j.append(",\"companion_fixture\":");j.string(kCompanion);j.append(",\"locomotion_fixture\":");j.string(kLocomotion);j.append(",\"companion_ready\":");j.boolean(companion);j.append(",\"binding_valid\":");j.boolean(companion&&o.binding.valid);j.append(",\"runtime_proven\":false}");}
}
