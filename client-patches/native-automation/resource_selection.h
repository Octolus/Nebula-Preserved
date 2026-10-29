#pragma once
#include <cstdint>
#include <cstring>

// Fixed original pet/locomotion callbacks. The host reacquires the current
// instantiated UI row and checks its real metadata class; never construct a row
// or write idAsset/isEmpty fields to manufacture a callback receiver.
namespace nebula_resource_selection {
enum class Kind { companion, locomotion };
enum class Result { rejected, dispatched, exception };
struct Snapshot {
    bool main_thread{},exact_profile{},authenticated{},same_session{},world_scene{};
    bool local_player{},owned_identity{},network_ready{},travelling{},other_action_pending{};
    bool exact_wheel{},wheel_visible{},one_selected_row{},receiver_real_class{},receiver_live{};
    bool row_active{},button_interactable{},entitlement_current{},exact_resource_id{};
    bool empty_row{},requested_remove{};
    void *receiver{};
};
struct Api {
    // Must resolve MethodInfo from the declared class and verify native pointer
    // game_base+rva, exact argcount==0, instance void return, actual class identity.
    void *(*pinned_method)(const char *class_name,const char *method,std::uint32_t rva);
    void *(*runtime_invoke)(void *method,void *receiver,void **args,void **exception);
};
inline Result dispatch(Kind kind,const Snapshot &s,const Api &api) {
    if(kind!=Kind::companion&&kind!=Kind::locomotion)return Result::rejected;
    if(!s.main_thread||!s.exact_profile||!s.authenticated||!s.same_session||!s.world_scene||
       !s.local_player||!s.owned_identity||!s.network_ready||s.travelling||s.other_action_pending||
       !s.exact_wheel||!s.wheel_visible||!s.one_selected_row||!s.receiver_real_class||!s.receiver_live||
       !s.row_active||!s.button_interactable||!s.exact_resource_id||!s.receiver||
       s.empty_row!=s.requested_remove||(!s.requested_remove&&!s.entitlement_current)||
       !api.pinned_method||!api.runtime_invoke)return Result::rejected;
    const bool pet=kind==Kind::companion;
    void *method=api.pinned_method(pet?"PetPrefab":"LocomotionPrefab","OnClick",pet?0x4c0b00:0x4b9be0);
    if(!method)return Result::rejected;
    void *exception=nullptr;
    api.runtime_invoke(method,s.receiver,nullptr,&exception);
    return exception?Result::exception:Result::dispatched;
}
// A callback dispatch is not completion. Root must observe original owner
// selection, selected UI row and peer companion/locomotion state separately.
}
