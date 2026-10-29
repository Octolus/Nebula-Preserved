// Source-backed root wheel, carousel, panel and row-selection overlay.
// Include after shared IL2CPP helpers and resource_ui_core.inc.
namespace resource_navigation_core {
namespace nrn=nebula_resource_navigation;
constexpr const char*kCompanion="A0IQgRXmw2UMG8T5UGrVE022o7Id25GU";
constexpr const char*kLocomotion="AJ7C1vNaTXDE2G5xRD5Uq4Tqv22a775K";
std::uint64_t hash_text(const char*s){std::uint64_t h=1469598103934665603ull;for(;s&&*s;++s){h^=std::uint8_t(*s);h*=1099511628211ull;}return h;}
bool same_base(const nrn::Binding&a,const nrn::Binding&b){return a.session_hash==b.session_hash&&a.local_guid_hash==b.local_guid_hash&&a.scene_hash==b.scene_hash&&a.local_net_id==b.local_net_id&&a.manager_instance_id==b.manager_instance_id;}
struct Tracker{nrn::Binding last{};std::uint64_t epoch{};bool initialized{};};
struct View{
 nrn::Binding binding{};void*manager{};void*player{};void*input{};void*input_menu{};void*menu{};void*wheel{};void*event_system{};void*open_object{};void*row_object{};
 bool root_visible{},wheel_visible{},target_selected{},target_ready{};
};
bool companion(nrn::Action a){return a==nrn::Action::PrepareCompanionSelect||a==nrn::Action::PrepareCompanionRemove;}
bool removing(nrn::Action a){return a==nrn::Action::PrepareCompanionRemove||a==nrn::Action::PrepareLocomotionRemove;}

struct Adapter final:nrn::Host{
 void*owner{};Tracker&tracker;View view{};Adapter(void*o,Tracker&t):owner(o),tracker(t){}
 bool bind(void*manager,void*local,nrn::Binding&out,const char*&reason){
  char digest[65]{},guid[257]{},info_guid[257]{},player_guid[257]{},scene[128]{};out={};
  void*memory=field<void*>(manager,0x2c0);void*info=memory?field<void*>(memory,0x10):nullptr;void*player=info?field<void*>(info,0x30):nullptr;
  if(singleton(api.object_class(owner),"_singleton")!=owner||!session_digest(owner,digest)||!managed_string(field<void*>(owner,0xe8),guid,sizeof guid)||!guid[0]||!active_scene(scene,sizeof scene)||!scene[0]||
     !typed(local,"NetworkIdentity","Mirror",true)||!field<std::uint8_t>(local,0x1a)||!field<std::uint8_t>(local,0x1b)||
     !typed(memory,"Memory","Assets.Scripts.Memories")||!typed(info,"PlayerInfo","Assets.Scripts.Memories")||!typed(player,"NebulaPlayer","",true)||
     !field<std::uint8_t>(player,0x9c)||field<void*>(player,0xf8)!=local||
     !managed_string(field<void*>(info,0x18),info_guid,sizeof info_guid)||!info_guid[0]||!managed_string(field<void*>(player,0xa0),player_guid,sizeof player_guid)||!player_guid[0]||
     std::strcmp(guid,info_guid)||std::strcmp(guid,player_guid)){
   SecureZeroMemory(digest,sizeof digest);SecureZeroMemory(guid,sizeof guid);SecureZeroMemory(info_guid,sizeof info_guid);SecureZeroMemory(player_guid,sizeof player_guid);reason="resource_navigation_owned_identity_guard";return false;
  }
  std::uint32_t player_info_net_id=0;if(!resource_player_info_net_id_exact(info,local,player_info_net_id)){reason="resource_navigation_player_info_netid_guard";return false;}
  void*box=nullptr;void*m=method(api.object_class(manager),"GetInstanceID",0,0x1b8b190);int id=0;
  if(!::invoke(m,manager,nullptr,box)||!boxed_int(box,id)||!id){reason="resource_navigation_manager_guard";return false;}
  out.session_hash=hash_text(digest);out.local_guid_hash=hash_text(guid);out.scene_hash=hash_text(scene);out.local_net_id=field<std::uint32_t>(local,0x28);out.manager_instance_id=id;out.valid=out.session_hash&&out.local_guid_hash&&out.scene_hash&&out.local_net_id;
  SecureZeroMemory(digest,sizeof digest);SecureZeroMemory(guid,sizeof guid);SecureZeroMemory(info_guid,sizeof info_guid);SecureZeroMemory(player_guid,sizeof player_guid);
  if(!tracker.initialized||!same_base(tracker.last,out)){tracker.last=out;tracker.initialized=true;++tracker.epoch;}out.generation_epoch=tracker.epoch;return out.valid;
 }
 bool build(nrn::Action action,const char*&reason){
  view={};void*local=nullptr;auto network=observe_network(local);view.manager=singleton(klass(script_image,"","ManagerInstance"),"_singleton");
  if(!derived_unity(view.manager,"ManagerInstance")||field<std::uint8_t>(view.manager,0x122)||std::strcmp(nac::network_reason(network),"ready")||!bind(view.manager,local,view.binding,reason))return false;
  void*memory=field<void*>(view.manager,0x2c0);void*info=memory?field<void*>(memory,0x10):nullptr;view.player=info?field<void*>(info,0x30):nullptr;
  view.input=view.player?field<void*>(view.player,0x60):nullptr;view.input_menu=view.input?field<void*>(view.input,0x40):nullptr;
  view.menu=field<void*>(view.manager,0x1c8);const bool pet=companion(action);const char*wheel_type=pet?"MenuWheelPets":"MenuWheelLocomotions";const char*open_name=pet?"Pets":"Locomotions";const char*row_type=pet?"PetPrefab":"LocomotionPrefab";const char*fixture=pet?kCompanion:kLocomotion;
  view.wheel=view.menu?field<void*>(view.menu,pet?0x90:0x98):nullptr;view.event_system=view.menu?field<void*>(view.menu,0x78):nullptr;
  if(!typed(view.input,"NebulaInput","Assets.Scripts.NebulaPlayers",true)||!typed(view.input_menu,"NebulaInputMenuWheel","Assets.Scripts.NebulaPlayers",true)||
     !typed(view.menu,"MenuWheel","",true)||!typed(view.wheel,wheel_type,"",true)||!typed(view.event_system,"EventSystem","UnityEngine.EventSystems",true)){reason="resource_navigation_menu_guard";return false;}
  bool active=false;view.root_visible=field<std::uint8_t>(view.manager,0x1d9)&&active_hierarchy(component_game_object(view.menu),active)&&active;
  int count=0;void**items=nullptr;const char*failure=nullptr;if(!list_items(field<void*>(view.menu,0xc8),count,items,failure)||count<1||count>32){reason=failure?failure:"resource_navigation_contents_guard";return false;}
  unsigned open_matches=0;for(int i=0;i<count;++i){char name[65]{};if(!typed(items[i],"GameObject","UnityEngine",true)||!object_name(items[i],name,sizeof name)){reason="resource_navigation_content_name_guard";return false;}if(!std::strcmp(name,open_name)){++open_matches;view.open_object=items[i];}}
  if(open_matches!=1){reason=open_matches?"resource_navigation_open_ambiguous":"resource_navigation_open_missing";return false;}
  view.wheel_visible=view.root_visible&&active_hierarchy(component_game_object(view.wheel),active)&&active;view.row_object=nullptr;view.target_selected=false;view.target_ready=false;
  if(view.wheel_visible){
   if(!list_items(field<void*>(view.wheel,0x90),count,items,failure)||count<1||count>256){reason=failure?failure:"resource_navigation_rows_guard";return false;}
   unsigned matches=0;for(int i=0;i<count;++i){void*button=items[i];if(!typed(button,"Button","UnityEngine.UI",true)){reason="resource_navigation_button_list_guard";return false;}void*object=component_game_object(button);void*row=component(object,script_image,"",row_type);if(!typed(row,row_type,"")){reason="resource_navigation_row_guard";return false;}bool empty=field<std::uint8_t>(row,0x28)!=0;char id[65]{};if(!empty&&!managed_string(field<void*>(row,0x30),id,sizeof id)){reason="resource_navigation_row_id_guard";return false;}if((removing(action)&&empty)||(!removing(action)&&!empty&&!std::strcmp(id,fixture))){++matches;view.row_object=object;}}
   if(matches!=1){reason=matches?"resource_navigation_row_ambiguous":"resource_navigation_row_missing";return false;}
   void*selected=nullptr,*m=method(klass(ui_image,"UnityEngine.EventSystems","EventSystem"),"get_currentSelectedGameObject",0,0x4f14f0);if(!::invoke(m,view.event_system,nullptr,selected)||(selected&&!typed(selected,"GameObject","UnityEngine",true))){reason="resource_navigation_selection_probe_guard";return false;}
   view.target_selected=selected==view.row_object;if(view.target_selected){void*button=nullptr;const char*ignored=nullptr;view.target_ready=button_ready(view.row_object,button,ignored);}
  }
  reason="ready";return true;
 }
 bool capture(nrn::Action a,nrn::Observation&o,const char*&r) noexcept override{if(!build(a,r))return false;o.binding=view.binding;o.root_visible=view.root_visible;o.wheel_visible=view.wheel_visible;o.target_selected=view.target_selected;o.target_ready=view.target_ready;return true;}
 bool open_root(nrn::Action a,const char*&r) noexcept override{
  if(!build(a,r)||view.root_visible||field<std::uint8_t>(view.manager,0x1d9)){r="resource_navigation_root_state_guard";return false;}
  void*chat=field<void*>(view.manager,0x150);void*interactor=field<void*>(view.player,0x50);void*bubbles=field<void*>(view.manager,0xb8);
  if(!typed(chat,"Chat","",true)||field<std::uint8_t>(chat,0xc0)||field<std::uint8_t>(view.manager,0x1dc)||
     !typed(interactor,"NebulaInteractor","Assets.Scripts.NebulaPlayers",true)||!typed(bubbles,"BubbleManager","",true)||
     !typed(field<void*>(view.menu,0x50),"GameObject","UnityEngine",true)||!typed(field<void*>(view.menu,0x58),"GameObject","UnityEngine",true)||
     !typed(field<void*>(view.menu,0x60),"GameObject","UnityEngine",true)||!typed(field<void*>(view.menu,0x68),"GameObject","UnityEngine",true)||
     !typed(field<void*>(view.menu,0x70),"GameObject","UnityEngine",true)){r="resource_navigation_root_operand_guard";return false;}
  void*m=method(api.object_class(view.input_menu),"Open",0,0x5f0be0);void*result=nullptr;if(!m||!::invoke(m,view.input_menu,nullptr,result)){r="resource_navigation_root_callback_guard";return false;}r="resource_navigation_root_callback_started";return true;}
 bool open_panel(nrn::Action a,const char*&r) noexcept override{
  if(!build(a,r)||!view.root_visible||view.wheel_visible){r="resource_navigation_panel_state_guard";return false;}
  void*selector=field<void*>(view.menu,0xb0);void*selector_up=field<void*>(view.menu,0xb8);void*selector_down=field<void*>(view.menu,0xc0);
  void*persist=field<void*>(owner,0x240);int existing_count=0;void**existing_items=nullptr;const char*list_reason=nullptr;
  if(!typed(selector,"RectTransform","UnityEngine",true)||!typed(selector_up,"RectTransform","UnityEngine",true)||!typed(selector_down,"RectTransform","UnityEngine",true)||
     !typed(persist,"Persistency","Assets.Scripts.Memories",true)||!typed(field<void*>(view.wheel,0x30),"EventSystem","UnityEngine.EventSystems",true)||
     !typed(field<void*>(view.wheel,0x80),"GameObject","UnityEngine",true)||!typed(field<void*>(view.wheel,0x88),"Sprite","UnityEngine",true)||
     !list_items(field<void*>(view.wheel,0x90),existing_count,existing_items,list_reason)||existing_count<0||existing_count>256||
     !typed(field<void*>(view.wheel,0xa0),"Scrollbar","UnityEngine.UI",true)||!typed(field<void*>(view.wheel,0xa8),"GameObject","UnityEngine",true)||
     !typed(field<void*>(view.wheel,0xb0),"LoadingCircle","",true)||!typed(field<void*>(view.wheel,0xb8),"GameObject","UnityEngine",true)){r=list_reason?list_reason:"resource_navigation_panel_operand_guard";return false;}
  void*arg=view.open_object;void*args[]{arg};void*result=nullptr;void*select=method(api.object_class(view.menu),"OnItemSelected",1,0x4bf850);
  const auto show_rva=companion(a)?std::uintptr_t(0x4be020):std::uintptr_t(0x4bc920);void*show=method(api.object_class(view.wheel),"Show",0,show_rva);
  if(!select||!show||!::invoke(select,view.menu,args,result)||!::invoke(show,view.wheel,nullptr,result)){r="resource_navigation_panel_callback_guard";return false;}r="resource_navigation_panel_callback_started";return true;
 }
 bool select(nrn::Action a,const char*&r) noexcept override{if(!build(a,r)||!view.root_visible||!view.wheel_visible||!view.row_object){r="resource_navigation_select_state_guard";return false;}void*button=nullptr;if(!button_ready(view.row_object,button,r))return false;return select_object(view.event_system,view.row_object,r);}
};
nrn::Module module;Tracker tracker{};const char*last_code="resource_navigation_idle";
bool pending(){return module.pending();}
const char*dispatch(void*owner,nrn::Action action,std::uint64_t now,std::uint64_t deadline,const char*&status){Adapter current(owner,tracker);auto result=module.begin(current,action,now,deadline);last_code=result.code;status=module.pending()?"started":"rejected";return last_code;}
void pump(void*owner,std::uint64_t now){if(!module.pending())return;Adapter current(owner,tracker);auto result=module.poll(current,now);last_code=result.code;}
void snapshot(Json&j){j.append(",\"resource_navigation\":{\"pending\":");j.boolean(pending());j.append(",\"last_code\":");j.string(last_code);j.append(",\"runtime_proven\":false}");}
}
