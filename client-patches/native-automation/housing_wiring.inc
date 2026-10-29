// Included after housing_native.inc and BEFORE add_snapshot/publish.
const char *housing_last_code="housing_idle";
uint32_t housing_requests{},housing_invoked{};
enum class HousingPhase {idle,opening,inventory,saving,travelling,personal_menu};
struct HousingPending {
    HousingPhase phase{HousingPhase::idle};uint64_t generation{},started{},deadline{};
    char session[65]{},instance[257]{},target[65]{},table[65]{},expected_scene[65]{};
    bool transition_seen{},native_receipt{};
};
HousingPending housing_operation{};
const char *housing_operation_code="housing_idle";
bool housing_uncertain{};
bool housing_pending(){return housing_uncertain||housing_operation.phase!=HousingPhase::idle;}
bool housing_context_identity(void *owner,char session[65],char instance[257]) {
    void *space=nullptr;
    return housing_base_ready(owner,space)&&session_digest(owner,session)&&
        managed_string(field<void*>(space,0x248),instance,257)&&instance[0];
}
bool housing_save_label(void *owner,char value[257]) {
    HousingNativeContext c{};if(!housing_context(owner,c,true))return false;
    void *ui=field<void*>(c.manager,0x18);if(!typed(ui,"HousingUI","",true))return false;
    void *popup=component(field<void*>(ui,0x40),script_image,"","HousingUISaveChangesPopUp");
    if(!typed(popup,"HousingUISaveChangesPopUp","",true)||field<void*>(popup,0x18)!=c.manager)return false;
    void *text=field<void*>(popup,0x20),*out=nullptr;
    return typed(text,"Text","UnityEngine.UI",true)&&
        invoke(method(api.object_class(text),"get_text",0,0x5f5660),text,nullptr,out)&&managed_string(out,value,257);
}
void service_housing(void *owner,uint64_t now) {
    if(housing_uncertain||!housing_pending()||now<=housing_operation.started)return;
    char session[65]{},instance[257]{};
    if(!typed(owner,"PS4Info","",true)||!session_digest(owner,session)||std::strcmp(session,housing_operation.session)) {
        housing_operation.phase=HousingPhase::idle;housing_operation_code="housing_session_changed";return;
    }
    if(now>=housing_operation.deadline){housing_operation.phase=HousingPhase::idle;housing_uncertain=true;
        housing_operation_code="housing_timeout_unproven_restart_required";return;}
    void *space=nullptr;const bool world_ready=housing_base_ready(owner,space);
    if(!world_ready){housing_operation.transition_seen=true;return;}
    if(!managed_string(field<void*>(space,0x248),instance,sizeof instance)||!instance[0])return;
    if(housing_operation.phase==HousingPhase::travelling) {
        char global[257]{};
        if(!managed_string(field<void*>(space,0x250),global,sizeof global))return;
        if(std::strcmp(instance,housing_operation.instance)&&!std::strcmp(global,housing_operation.expected_scene)) {
            housing_operation.native_receipt=true;housing_operation.phase=HousingPhase::idle;
            housing_operation_code="housing_travel_fresh_allocation_observed";
        }
        return;
    }
    if(std::strcmp(instance,housing_operation.instance)) {
        housing_operation.phase=HousingPhase::idle;housing_operation_code="housing_allocation_changed";return;
    }
    if(housing_operation.phase==HousingPhase::personal_menu) {
        void *n=field<void*>(space,0xe0),*item=nullptr;
        if(typed(n,"NavigatorSelector","",true)&&field<uint8_t>(n,0x40)&&!field<uint8_t>(n,0xf0)&&
           housing_list_item(field<void*>(n,0x88),field<int32_t>(n,0xd0),item)&&typed(item,"NavigatorItem","",true)) {
            housing_operation.native_receipt=true;housing_operation.phase=HousingPhase::idle;
            housing_operation_code="housing_personal_menu_observed";
        }
        return;
    }
    HousingNativeContext c{};if(!housing_context(owner,c,true))return;
    if(housing_operation.phase==HousingPhase::opening) {
        void *ui=field<void*>(c.manager,0x18);void *s=field<void*>(ui,0x20);
        if(typed(ui,"HousingUI","",true)&&housing_active(ui)&&field<void*>(ui,0x58)==c.manager&&
           typed(s,"HousingUIContentSelector","",true)&&housing_active(s)&&field<void*>(s,0x38)==c.manager&&
           field<int32_t>(c.manager,0x54)==0) {
            housing_operation.native_receipt=true;housing_operation.phase=HousingPhase::idle;
            housing_operation_code="housing_open_callback_generation_observed";
        }
    } else if(housing_operation.phase==HousingPhase::inventory) {
        void *asset=field<void*>(c.focus,0x20);
        if(field<int32_t>(c.manager,0x54)==1&&derived_unity(asset,"HousingAsset")&&housing_active(asset)&&
           housing_text_is(field<void*>(asset,0x18),housing_operation.target)&&
           housing_text_is(field<void*>(asset,0x38),housing_operation.table)) {
            housing_operation.native_receipt=true;housing_operation.phase=HousingPhase::idle;
            housing_operation_code="housing_inventory_instantiation_observed";
        }
    } else if(housing_operation.phase==HousingPhase::saving) {
        char label[257]{};
        if(housing_save_label(owner,label)) {
            if(!std::strcmp(label,"Saving failed.")) {
                housing_operation.phase=HousingPhase::idle;housing_operation_code="housing_native_save_failed";
            } else if(!std::strcmp(label,"Changes saved successfully.")) {
                // Start required the question text. Only the native HTTP part1
                // receive callback changes it to this success text (3a5c20).
                housing_operation.native_receipt=true;housing_operation.phase=HousingPhase::idle;
                housing_operation_code="housing_native_save_ack_observed_durability_unproven";
            }
        }
    }
}
const char *dispatch_housing(void *owner,const char *argument,uint64_t now,uint64_t deadline,const char *&status) {
    struct Entry {const char* name;HousingCommand command;float axis;};
    static const Entry entries[]={
        {"open",HousingCommand::Open,0},
        {"organize",HousingCommand::Organize,0},{"menu",HousingCommand::Menu,0},
        {"menu.left",HousingCommand::MenuLeft,0},{"menu.right",HousingCommand::MenuRight,0},
        {"menu.up",HousingCommand::MenuUp,0},{"menu.down",HousingCommand::MenuDown,0},
        {"cancel",HousingCommand::CancelPlacement,0},{"place",HousingCommand::ConfirmPlacement,0},
        {"save",HousingCommand::Save,0},{"move.left",HousingCommand::MoveHorizontal,-0.5f},
        {"move.right",HousingCommand::MoveHorizontal,0.5f},{"move.up",HousingCommand::MoveVertical,0.5f},
        {"move.down",HousingCommand::MoveVertical,-0.5f},{"look.left",HousingCommand::RotateHorizontal,-0.5f},
        {"look.right",HousingCommand::RotateHorizontal,0.5f},{"look.up",HousingCommand::RotateVertical,0.5f},
        {"look.down",HousingCommand::RotateVertical,-0.5f},{"raise",HousingCommand::Raise,0.5f},
        {"lower",HousingCommand::Lower,0.5f},{"rotate.left",HousingCommand::RotateLeft,0},
        {"rotate.right",HousingCommand::RotateRight,0},{"personal.menu",HousingCommand::PersonalMenu,0},
        {"interact",HousingCommand::InteractSelected,0},{"interaction.left",HousingCommand::InteractionLeft,0},
        {"interaction.right",HousingCommand::InteractionRight,0}};
    if(housing_pending()){status="rejected";return "housing_action_overlap";}
    ++housing_requests;
    HousingPending candidate{};candidate.generation=housing_operation.generation+1;candidate.started=now;
    candidate.deadline=deadline<now+30000?deadline:now+30000;
    if(!housing_context_identity(owner,candidate.session,candidate.instance)) {
        status="rejected";return "housing_identity_unavailable";
    }
    if(!std::strcmp(argument,"save")) {
        HousingNativeContext c{};char label[257]{};
        if(!housing_context(owner,c,true)||field<int32_t>(c.manager,0x54)==1){status="rejected";return "housing_save_context";}
        void *ui=field<void*>(c.manager,0x18);
        if(!typed(ui,"HousingUI","",true)||!housing_call(ui,"ShowSaveChangesPopUp",0,0x528a20)||
           !housing_save_label(owner,label)||std::strcmp(label,"Do you want to keep your changes?")) {
            status="rejected";return "housing_save_fresh_question_required";
        }
        candidate.phase=HousingPhase::saving;
    } else if(!std::strcmp(argument,"open"))candidate.phase=HousingPhase::opening;
    else if(!std::strcmp(argument,"personal.menu"))candidate.phase=HousingPhase::personal_menu;
    HousingNativeResult result{false,"housing_argument_rejected"};
    bool matched=false;
    for(const auto &e:entries)if(!std::strcmp(argument,e.name)){
        result=housing_native_command(owner,e.command,"","",e.axis);matched=true;break;
    }
    if(!matched&&!std::strncmp(argument,"travel|",7)&&argument[7]) {
        result=housing_native_command(owner,HousingCommand::TravelSelected,argument+7);
        candidate.phase=HousingPhase::travelling;std::strcpy(candidate.target,argument+7);
        // Only recovered logical/apartment key whose shipped scene differs.
        // Dispatch still validates the exact original logical navigator row.
        std::strcpy(candidate.expected_scene,!std::strcmp(argument+7,"SorcerersEyrie")?"SorcerersEyrie1":argument+7);
    }
    const bool activate=!std::strncmp(argument,"activate|",9);
    const bool replace=!std::strncmp(argument,"replace|",8);
    const bool remove=!std::strncmp(argument,"remove|",7);
    if(!matched&&(activate||replace||remove)) {
        const size_t prefix=activate?9:replace?8:7;
        char table[65]{},id[65]{};const char *sep=std::strchr(argument+prefix,'|');
        if(sep&&sep>argument+prefix&&std::strlen(sep+1)>0&&std::strlen(sep+1)<sizeof id&&
           static_cast<size_t>(sep-(argument+prefix))<sizeof table&&!std::strchr(sep+1,'|')) {
            std::memcpy(table,argument+prefix,size_t(sep-(argument+prefix)));
            std::strcpy(id,sep+1);
            result=housing_native_command(owner,activate?HousingCommand::ActivateSelected:
                replace?HousingCommand::ReplaceSelected:HousingCommand::RemoveSelected,id,table);
            if(activate){candidate.phase=HousingPhase::inventory;std::strcpy(candidate.target,id);std::strcpy(candidate.table,table);}
        }
    }
    housing_last_code=result.code;
    if(result.invoked){++housing_invoked;status="started";housing_operation=candidate;
        housing_operation_code=housing_pending()?"housing_waiting_fresh_native_receipt":"housing_callback_invoked";
    }else status="rejected";
    return housing_last_code;
}
void add_housing_snapshot(Json &j,void *owner) {
    j.append(",\"housing\":{\"requests\":");j.integer(housing_requests);
    j.append(",\"callbacks_invoked\":");j.integer(housing_invoked);
    j.append(",\"last_code\":");j.string(housing_last_code);
    j.append(",\"pending\":");j.boolean(housing_pending());
    j.append(",\"uncertain_timeout_quarantine\":");j.boolean(housing_uncertain);
    j.append(",\"generation\":");j.integer(housing_operation.generation);
    j.append(",\"operation_code\":");j.string(housing_operation_code);
    j.append(",\"fresh_native_receipt_observed\":");j.boolean(housing_operation.native_receipt);
    HousingNativeContext c{};const bool ready=housing_context(owner,c,false);
    j.append(",\"personal_space_ready\":");j.boolean(ready);
    j.append(",\"owner_alone_guard\":");HousingNativeContext writable{};
    j.boolean(housing_context(owner,writable,true));
    if(ready) {
        const int mode=field<int32_t>(c.manager,0x54);
        j.append(",\"mode\":");j.string(mode==0?"ui":mode==1?"placing":mode==2?"organizing":"invalid");
        j.append(",\"placed_asset_present\":");j.boolean(derived_unity(field<void*>(c.focus,0x20),"HousingAsset"));
        j.append(",\"selected_asset_present\":");j.boolean(derived_unity(field<void*>(c.manager,0x58),"HousingAsset"));
        void *f=field<void*>(c.manager,0x30);
        if(typed(f,"HousingFurnishing","",true)) {
            j.append(",\"placement_space_used\":");j.integer(uint32_t(field<int32_t>(f,0x58)));
            j.append(",\"layout_loaded\":");j.boolean(field<uint8_t>(f,0xb0)!=0);
        }
    }
    j.append(",\"durable_save_proven\":false,\"fresh_client_load_proven\":false,\"peer_sync_proven\":false}");
}
