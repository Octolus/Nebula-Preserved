// Include inside V16 automation.cpp anonymous namespace AFTER boxed_int,
// component_game_object and active_hierarchy helpers. No new exports.
// Caller runs from authenticated NAC main-thread command dispatch. Return means
// callback invoked; it does not mean asynchronous save/load/replication completed.
enum class HousingCommand {
    Open, Organize, Menu, MenuLeft, MenuRight, MenuUp, MenuDown, ActivateSelected,
    ReplaceSelected, RemoveSelected, CancelPlacement, ConfirmPlacement, Save,
    MoveHorizontal, MoveVertical, RotateHorizontal, RotateVertical,
    Raise, Lower, RotateLeft, RotateRight, PersonalMenu, TravelSelected,
    InteractSelected, InteractionLeft, InteractionRight, ConfirmGeneric
};
struct HousingNativeResult {bool invoked{};const char* code="housing_not_ready";};
struct HousingNativeContext {void *space{},*manager{},*camera{},*focus{},*selector{};};
bool housing_active(void *component) {
    void *go=component_game_object(component);bool active=false;
    return go&&active_hierarchy(go,active)&&active;
}
bool housing_call(void *receiver,const char* name,int argc,uintptr_t rva,void **args=nullptr) {
    void *out=nullptr;
    return receiver&&invoke(method(api.object_class(receiver),name,argc,rva),receiver,args,out);
}
bool housing_list_item(void *list,int index,void *&item) {
    item=nullptr;
    if(!list||index<0||!readable(list,0x20))return false;
    int count=field<int32_t>(list,0x18);
    void *array=field<void*>(list,0x10);
    if(count<0||count>512||index>=count||!readable(array,0x20))return false;
    auto length=field<uintptr_t>(array,0x18);
    if(length>512||static_cast<uintptr_t>(count)>length||!readable(array,0x20+sizeof(void*)*length))return false;
    item=field<void*>(array,0x20+sizeof(void*)*index);return item!=nullptr;
}
bool housing_text_is(void *text,const char *expected) {
    char value[257]{};return expected&&managed_string(text,value,sizeof value)&&!std::strcmp(value,expected);
}
// Original PlayerInfo.get_NetId616a70 follows its current NebulaPlayer identity.
// The private info+10 field is not populated by the shipped constructor.
bool housing_player_info_net_id(void *info,uint32_t &value) {
    value=0;
    if(GetCurrentThreadId()!=thread||!initialized||disabled||
       !typed(info,"PlayerInfo","Assets.Scripts.Memories"))return false;
    void *player=field<void*>(info,0x30);
    if(!typed(player,"NebulaPlayer","",true))return false;
    void *identity=field<void*>(player,0xf8);
    if(!typed(identity,"NetworkIdentity","Mirror",true)||!readable(identity,0x2c))return false;
    void *getter=method(klass(script_image,"Assets.Scripts.Memories","PlayerInfo"),"get_NetId",0,0x616a70),*box=nullptr;
    if(!invoke(getter,info,nullptr,box)||!typed(box,"UInt32","System")||!readable(box,0x14))return false;
    value=field<uint32_t>(box,0x10);
    return value&&value==field<uint32_t>(identity,0x28);
}
bool housing_base_ready(void *owner,void *&space) {
    space=nullptr;
    if(GetCurrentThreadId()!=thread||!initialized||disabled||!typed(owner,"PS4Info","",true)||
       singleton(klass(script_image,"","PS4Info"),"_singleton")!=owner||
       !readable(owner,0x100)||field<uint8_t>(owner,0x95)||
       !field<uint8_t>(owner,0xfa))return false;
    space=singleton(klass(script_image,"","ManagerInstance"),"_singleton");
    if(!(derived_unity(space,"ManagerInstance")&&readable(space,0x310)&&
        field<uint8_t>(space,0x121)&&!field<uint8_t>(space,0xa0)&&!field<uint8_t>(space,0xa1)&&
        !field<uint8_t>(space,0x120)&&!field<uint8_t>(space,0x122)&&!field<uint8_t>(space,0x123)))return false;
    void *identity=nullptr;auto network=observe_network(identity);
    if(!network.probe_ok||!network.authenticated||!network.connected||!network.ready||
       !network.connection_ready||!network.local_player_alive||
       !typed(identity,"NetworkIdentity","Mirror",true)||!field<uint8_t>(identity,0x1b))return false;
    // PS4Info+99/+9a remain diagnostic only: both serialized false in shipped Steam InitLOAD;
    // original Mirror probes above establish actual authenticated connected ownership.
    void *memory=field<void*>(space,0x2c0),*info=field<void*>(memory,0x10),*player=field<void*>(info,0x30);
    uint32_t info_net_id=0;
    if(!typed(memory,"Memory","Assets.Scripts.Memories")||!typed(info,"PlayerInfo","Assets.Scripts.Memories")||
       !typed(player,"NebulaPlayer","",true)||!field<uint8_t>(player,0x9c)||field<void*>(player,0xf8)!=identity||
       !housing_player_info_net_id(info,info_net_id)||info_net_id!=field<uint32_t>(identity,0x28))return false;
    char owner_guid[257]{},info_guid[257]{},player_guid[257]{};
    return managed_string(field<void*>(owner,0xe8),owner_guid,sizeof owner_guid)&&owner_guid[0]&&
        managed_string(field<void*>(info,0x18),info_guid,sizeof info_guid)&&
        managed_string(field<void*>(player,0xa0),player_guid,sizeof player_guid)&&
        !std::strcmp(owner_guid,info_guid)&&!std::strcmp(owner_guid,player_guid);
}
bool housing_context(void *owner,HousingNativeContext &c,bool write,bool entering=false) {
    if(!housing_base_ready(owner,c.space)||!derived_unity(c.space,"ManagerInstancePersonalSpace")||
       singleton(klass(script_image,"","ManagerInstancePersonalSpace"),"_singletonPersonalSpace")!=c.space||
       !readable(c.space,0x328))return false;
    char local[257]{},host[257]{};
    if(!managed_string(field<void*>(owner,0xe8),local,sizeof local)||!local[0]||
       !managed_string(field<void*>(c.space,0x320),host,sizeof host)||!host[0])return false;
    if(write) {
        if(std::strcmp(local,host))return false;
        // Same original gate used by HousingManager.Initialize6c4080:
        // only an owner with no Memory.remotes can organize furniture.
        void *memory=field<void*>(c.space,0x2c0),*box=nullptr;
        if(!typed(memory,"Memory","Assets.Scripts.Memories"))return false;
        void *remotes=field<void*>(memory,0x18);int count=-1;
        if(!remotes||!invoke(method(api.object_class(remotes),"get_Count",0,0xb39fc0),remotes,nullptr,box)||
           !boxed_int(box,count)||count!=0)return false;
    }
    c.manager=field<void*>(c.space,0x310);
    if(!derived_unity(c.manager,"HousingManager")||!housing_active(c.manager)||!readable(c.manager,0x88))return false;
    c.camera=field<void*>(c.manager,0x28);
    if(!typed(c.camera,"HousingCamera","",true)||(!entering&&field<void*>(c.camera,0x50)!=c.manager))return false;
    c.focus=field<void*>(c.camera,0x20);
    if(!typed(c.focus,"HousingFocusPoint","",true)||(!entering&&field<void*>(c.focus,0x28)!=c.manager))return false;
    return true;
}
HousingNativeResult housing_native_command(void *owner,HousingCommand command,
                                           const char *expectedId="",const char *expectedTable="",float value=0) {
    HousingNativeContext c{};
    // Navigator and interactions also operate in public scenes.
    const bool nav=command==HousingCommand::PersonalMenu||command==HousingCommand::TravelSelected;
    const bool interaction=command==HousingCommand::InteractSelected||command==HousingCommand::InteractionLeft||
        command==HousingCommand::InteractionRight||command==HousingCommand::ConfirmGeneric;
    if(nav||interaction) {if(!housing_base_ready(owner,c.space))return {};}
    else if(!housing_context(owner,c,true,command==HousingCommand::Open))return {false,"housing_owner_or_remote_guard"};
    auto outcome=[](bool ok){return HousingNativeResult{ok,ok?"housing_callback_invoked":"housing_callback_rejected"};};
    const int state=c.manager?field<int32_t>(c.manager,0x54):-1;
    if(nav) {
        void *n=field<void*>(c.space,0xe0);
        if(!typed(n,"NavigatorSelector","",true)||!housing_active(n))return {false,"housing_navigator_missing"};
        if(command==HousingCommand::PersonalMenu)
            return outcome(housing_call(n,"OnClickPersonalSpaceDelay",0,0x47d070));
        if(!field<uint8_t>(n,0x40)||field<uint8_t>(n,0xf0)||field<uint8_t>(n,0x120))return {false,"housing_navigator_busy"};
        void *item=nullptr;
        if(!housing_list_item(field<void*>(n,0x88),field<int32_t>(n,0xd0),item)||
           !typed(item,"NavigatorItem","",true)||!housing_text_is(field<void*>(item,0x28),expectedId))
            return {false,"housing_travel_selection_mismatch"};
        return outcome(housing_call(n,"OnOpenScene",0,0x47d130));
    }
    if(interaction) {
        if(command==HousingCommand::ConfirmGeneric) {
            void *m=singleton(klass(script_image,"","InteractionMenu"),"_singleton");bool visible=false;
            if(!typed(m,"InteractionMenu","",true)||!active_hierarchy(field<void*>(m,0x40),visible)||
               !visible||!field<void*>(m,0x50))return {false,"housing_generic_prompt_not_bound"};
            return outcome(housing_call(m,"OnGenericWindowConfirm",0,0x47bbc0));
        }
        void *ui=field<void*>(c.space,0x2d0);
        if(!typed(ui,"UIInteractionMenu","Assets.Scripts.NebulaInteractors.UI",true)||!housing_active(ui))
            return {false,"housing_interaction_ui_not_active"};
        void *interactor=field<void*>(ui,0x40);
        if(!typed(interactor,"NebulaInteractor","Assets.Scripts.NebulaPlayers",true)||!field<uint8_t>(interactor,0x20))
            return {false,"housing_interactor_not_ready"};
        if(command==HousingCommand::InteractionLeft)return outcome(housing_call(ui,"SelectLeft",0,0x619a80));
        if(command==HousingCommand::InteractionRight)return outcome(housing_call(ui,"SelectRight",0,0x619b70));
        void *target=nullptr;
        if(!housing_list_item(field<void*>(interactor,0x28),field<int32_t>(ui,0x38),target)||
           (!typed(target,"LightTrigger","",true)&&
            !derived_unity(target,"NebulaSeat","Assets.Scripts.NebulaInteractors.Interactables"))||!housing_active(target))
            return {false,"housing_selected_target_not_light_or_seat"};
        // Sends through NebulaInteractor and original TCPClient; never receive-only Lights().
        return outcome(housing_call(ui,"Interact",0,0x619700));
    }
    switch(command) {
    case HousingCommand::Open: {
        // Same virtual Initialize callback invoked by both shipped housing
        // entry buttons (466bc0/435060); no editor state is fabricated here.
        void *ui=field<void*>(c.manager,0x18);
        if(!typed(ui,"HousingUI","",true))return {false,"housing_ui_missing"};
        if(field<void*>(ui,0x58)==c.manager&&housing_active(ui))return {false,"housing_already_open"};
        uintptr_t init=typed(c.manager,"HousingManager","",true)?0x6c4080:
            typed(c.manager,"HousingManagerBlueWaveHideout","",true)?0x6c31d0:
            typed(c.manager,"HousingManagerTheNebulian","",true)?0x6c32b0:0;
        if(!init)return {false,"housing_initialize_runtime_type_unreviewed"};
        return outcome(housing_call(c.manager,"Initialize",0,init));
    }
    case HousingCommand::Organize:
        if(state!=0)return {false,"housing_requires_ui"};
        return outcome(housing_call(c.manager,"SetOrganizeMode",0,0x6c5430));
    case HousingCommand::Menu:
        if(state==1)return {false,"housing_placement_pending"};
        return outcome(housing_call(c.manager,"SetUIMode",0,0x6c5e00));
    case HousingCommand::Save:
        if(state==1)return {false,"housing_placement_pending"};
        return outcome(housing_call(c.manager,"SaveAssetsAtServer",0,0x6c4dc0));
    case HousingCommand::ReplaceSelected:case HousingCommand::RemoveSelected:
        {void *asset=field<void*>(c.manager,0x58);
        if(state!=2||!derived_unity(asset,"HousingAsset")||!housing_active(asset)||!field<uint8_t>(asset,0x40)||
           !expectedId[0]||!expectedTable[0]||!housing_text_is(field<void*>(asset,0x18),expectedId)||
           !housing_text_is(field<void*>(asset,0x38),expectedTable))return {false,"housing_selection_missing_or_mismatched"};
        return outcome(housing_call(c.manager,command==HousingCommand::ReplaceSelected?"ReplaceSelectedAsset":"RemoveSelectedAsset",0,
                                   command==HousingCommand::ReplaceSelected?0x6c4660:0x6c4580));}
    case HousingCommand::CancelPlacement:
        if(state!=1)return {false,"housing_requires_placement"};
        if(!housing_call(c.focus,"RestorePlacedObject",0,0x6bb620)||field<void*>(c.focus,0x20))
            return {false,"housing_cancel_not_completed"};
        return outcome(housing_call(c.manager,"SetOrganizeMode",0,0x6c5430));
    case HousingCommand::ConfirmPlacement: {
        if(state!=1)return {false,"housing_requires_placement"};
        void *asset=field<void*>(c.focus,0x20);
        if(!derived_unity(asset,"HousingAsset")||field<uint8_t>(asset,0x41))return {false,"housing_bad_position"};
        const char* name=nullptr;uintptr_t rva=0;
        if(typed(asset,"HousingAssetGround","",true)){name="DropPlacedObjectGround";rva=0x6bb3c0;}
        else if(typed(asset,"HousingAssetFloor","",true)){name="DropPlacedObjectFloor";rva=0x6bb330;}
        else if(typed(asset,"HousingAssetWall","",true)){name="DropPlacedObjectWall";rva=0x6bb2c0;}
        else if(typed(asset,"HousingAssetCeiling","",true)){name="DropPlacedObjectCeiling";rva=0x6bb2c0;}
        if(!name||!housing_call(c.focus,name,0,rva)||field<void*>(c.focus,0x20))return {false,"housing_drop_not_completed"};
        return outcome(housing_call(c.manager,"SetOrganizeMode",0,0x6c5430));
    }
    case HousingCommand::MenuLeft:case HousingCommand::MenuRight:case HousingCommand::MenuUp:
    case HousingCommand::MenuDown:case HousingCommand::ActivateSelected: {
        if(state!=0)return {false,"housing_requires_ui"};
        void *ui=field<void*>(c.manager,0x18);if(!typed(ui,"HousingUI","",true))return {};
        void *s=field<void*>(ui,0x20);
        if(!typed(s,"HousingUIContentSelector","",true)||!housing_active(s)||field<uint8_t>(s,0x2c)||field<void*>(s,0x38)!=c.manager)return {};
        const char* name=nullptr;uintptr_t rva=0;
        if(command==HousingCommand::MenuLeft){name="MoveLeft";rva=0x6d0ab0;}
        if(command==HousingCommand::MenuRight){name="MoveRight";rva=0x6d0bc0;}
        if(command==HousingCommand::MenuUp){name="MoveUp";rva=0x6d0cc0;}
        if(command==HousingCommand::MenuDown){name="MoveDown";rva=0x6d0980;}
        if(command==HousingCommand::ActivateSelected) {
            void *button=nullptr;
            if(!housing_list_item(field<void*>(s,0x18),field<int32_t>(s,0x28),button)||
               field<void*>(s,0x20)!=button||!typed(button,"HousingUIButton","",true)||!housing_active(button)||!field<uint8_t>(button,0x58)||
               !housing_text_is(field<void*>(button,0x48),expectedId)||!housing_text_is(field<void*>(button,0x50),expectedTable))
                return {false,"housing_inventory_selection_mismatch"};
            name="ActivateSelected";rva=0x6d0830;
        }
        return outcome(housing_call(s,name,0,rva));
    }
    default:break;
    }
    if(state!=1&&state!=2)return {false,"housing_requires_placing_or_organizing"};
    const char* name=nullptr;uintptr_t rva=0;bool scalar=true;
    switch(command) {
    case HousingCommand::MoveHorizontal:name="MoveHorizontal";rva=0x6b67e0;break;
    case HousingCommand::MoveVertical:name="MoveVertical";rva=0x6b6810;break;
    case HousingCommand::RotateHorizontal:name="RotateHorizontal";rva=0x6b69e0;break;
    case HousingCommand::RotateVertical:name="RotateVertical";rva=0x6b6a70;break;
    case HousingCommand::Raise:name="RaisePlacedObject";rva=0x6b6840;break;
    case HousingCommand::Lower:name="LowerPlacedObject";rva=0x6b67b0;break;
    case HousingCommand::RotateLeft:name="RotatePlacedObjectLeft";rva=0x6b6a10;scalar=false;break;
    case HousingCommand::RotateRight:name="RotatePlacedObjectRight";rva=0x6b6a40;scalar=false;break;
    default:return {false,"housing_unknown_command"};
    }
    if((command==HousingCommand::Raise||command==HousingCommand::Lower||!scalar)&&state!=1)
        return {false,"housing_requires_placement"};
    if(scalar&&(!(value>=-1.f&&value<=1.f)))return {false,"housing_invalid_axis"};
    void *args[]={&value};return outcome(housing_call(c.camera,name,scalar?1:0,rva,scalar?args:nullptr));
}
