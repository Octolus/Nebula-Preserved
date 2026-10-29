// Included inside V16's anonymous namespace after all shared helpers.
struct EconomySharedCore final:nebula_economy_v16::SharedCore {
    bool context(void *owner,nebula_economy::Context&o) noexcept override {
        char scene[128]{},digest[65]{};auto desktop=current_desktop_proof();
        o.desktop_ok=desktop.probe_ok&&desktop.matches_session&&!desktop.receives_input;
        o.scene_nexus=active_scene(scene,sizeof(scene))&&!std::strcmp(scene,"Nexus");
        o.identity_current=::singleton(api.object_class(owner),"_singleton")==owner;
        void*manager=::singleton(klass(script_image,"","ManagerInstance"),"_singleton");
        o.manager_current=::derived_unity(manager,"ManagerInstance");o.in_space=field<uint8_t>(owner,0xfa)!=0;
        void*local=nullptr;auto n=observe_network(local);o.network_connected=n.connected;o.network_authenticated=n.authenticated;
        o.network_ready=n.ready;o.connection_ready=n.connection_ready;o.local_player_alive=n.local_player_alive;
        o.local_player_done=o.manager_current&&field<uint8_t>(manager,0x121);o.not_travelling=o.manager_current&&!field<uint8_t>(manager,0x122);
        o.session_same=economy_session_digest[0]&&session_digest(owner,digest)&&!std::strcmp(digest,economy_session_digest);
        SecureZeroMemory(digest,sizeof(digest));o.shop_bound=true;o.no_overlap=!preset_pending&&!remove_pending&&!save_pending;return true;
    }
    void*singleton(const char*type,const char*name) noexcept override{return ::singleton(klass(script_image,"",type),name);}
    bool typed(void*object,const char*type,const char*ns,bool unity) noexcept override{return ::typed(object,type,ns,unity);}
    bool derived_unity(void*object,const char*type,const char*ns) noexcept override{return ::derived_unity(object,type,ns);}
    void*pointer(void*object,size_t offset) noexcept override{return object&&readable(object,offset+8)?field<void*>(object,offset):nullptr;}
    int32_t int32(void*object,size_t offset) noexcept override{return object&&readable(object,offset+4)?field<int32_t>(object,offset):INT32_MIN;}
    uint8_t uint8(void*object,size_t offset) noexcept override{return object&&readable(object,offset+1)?field<uint8_t>(object,offset):0;}
    bool exact_string(void*value,const char*expected) noexcept override{char text[129]{};return managed_string(value,text,sizeof(text))&&!std::strcmp(text,expected);}
    bool list(void*value,int32_t&count,void**&items,const char*&reason) noexcept override{return list_items(value,count,items,reason);}
    void*game_object(void*component) noexcept override{return ::derived_unity(component,"Component","UnityEngine")?component_game_object(component):nullptr;}
    bool active(void*object,bool&value) noexcept override{return object&&active_hierarchy(object,value);}
    bool selected(void*event_system,void*&object) noexcept override{object=nullptr;void*m=::method(klass(ui_image,"UnityEngine.EventSystems","EventSystem"),"get_currentSelectedGameObject",0,0x4f14f0);return ::typed(event_system,"EventSystem","UnityEngine.EventSystems",true)&&::invoke(m,event_system,nullptr,object)&&(!object||::typed(object,"GameObject","UnityEngine",true));}
    bool uint_text(void*text,int&value) noexcept override{value=0;if(!::typed(text,"Text","UnityEngine.UI",true))return false;char raw[32]{};if(!managed_string(field<void*>(text,0xe0),raw,sizeof(raw)))return false;size_t n=std::strlen(raw);if(!n||(n>1&&raw[0]=='0'))return false;uint64_t parsed=0;for(size_t i=0;i<n;++i){if(raw[i]<'0'||raw[i]>'9'||parsed>(uint64_t(INT32_MAX)-unsigned(raw[i]-'0'))/10)return false;parsed=parsed*10+unsigned(raw[i]-'0');}value=int(parsed);return true;}
    void*method(const char*type,const char*name,unsigned args,uintptr_t rva) noexcept override{return ::method(klass(script_image,"",type),name,args,rva);}
    bool invoke(void*m,void*receiver,void**args) noexcept override{void*ignored=nullptr;return ::invoke(m,receiver,args,ignored);}
};
EconomySharedCore economy_core{};

bool economy_pending(){auto p=economy_module.machine().phase;using P=nebula_economy::Phase;return p==P::OpenWait||p==P::ClothingWait||p==P::ShopWait||p==P::GenderWait||p==P::TypeWait||p==P::OfferWait||p==P::BuyWait||p==P::CatalogWait;}
void service_economy(void*owner,uint64_t now){if(!economy_pending())return;nebula_economy_v16::Adapter host{economy_core,owner,nebula_economy::offer_wait_authorized(economy_module.machine(),now)};auto r=economy_module.service(host,now);economy_status=r.status;economy_code=r.code;if(!std::strcmp(r.status,"completed")||!std::strcmp(r.status,"rejected")||!std::strcmp(r.status,"error"))economy_callback_generation::disarm();}
const char*dispatch_economy(void*owner,nebula_economy::Action action,uint64_t now,const char*&status){
    char digest[65]{};if(!session_digest(owner,digest)){status="rejected";return "economy_session_guard";}
    if(!economy_session_digest[0])std::memcpy(economy_session_digest,digest,sizeof(digest));
    bool same=!std::strcmp(economy_session_digest,digest);SecureZeroMemory(digest,sizeof(digest));if(!same){status="rejected";return "economy_session_changed";}
    bool purchase=action==nebula_economy::Action::BuyCrystals||action==nebula_economy::Action::BuyNP;if(purchase)economy_callback_generation::arm();nebula_economy_v16::Adapter host{economy_core,owner};auto r=economy_module.dispatch(host,action,now,store_purchase_configured);if(purchase&&std::strcmp(r.status,"started"))economy_callback_generation::disarm();economy_status=r.status;economy_code=r.code;status=!std::strcmp(r.status,"pending")||!std::strcmp(r.status,"started")?"started":!std::strcmp(r.status,"completed")?"ok":r.status;return r.code;
}
