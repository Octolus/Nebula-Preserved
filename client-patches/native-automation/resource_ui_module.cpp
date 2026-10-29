#include "resource_ui_module.h"

namespace nebula_resource_ui {
namespace {
bool same(const Binding&a,const Binding&b) noexcept {
  return a.valid&&b.valid&&a.session_hash==b.session_hash&&
    a.local_guid_hash==b.local_guid_hash&&a.scene_hash==b.scene_hash&&
    a.generation_epoch==b.generation_epoch&&a.local_net_id==b.local_net_id&&
    a.manager_instance_id==b.manager_instance_id;
}
bool remove(Action a) noexcept {
  return a==Action::RemoveCompanion||a==Action::RemoveLocomotion;
}
}
void Module::reset() noexcept {
  action_=Action::SelectCompanion;phase_=Phase::Idle;binding_={};
  before_generation_=deadline_=0;code_="idle";
}
Result Module::begin(Host&host,Action action,std::uint64_t now,std::uint64_t deadline) noexcept {
  if(phase_!=Phase::Idle)return{Phase::Failed,"resource_action_overlap"};
  if(deadline<=now)return{Phase::Failed,"resource_deadline_guard"};
  Observation observation{};nebula_resource_selection::Snapshot selection{};const char*reason=nullptr;
  if(!host.capture(action,true,observation,selection,reason)||!observation.binding.valid)
    return{Phase::Failed,reason?reason:"resource_capture_guard"};
  if(selection.requested_remove!=remove(action))return{Phase::Failed,"resource_remove_contract_guard"};
  const auto dispatched=host.invoke(action,selection,reason);
  if(dispatched==nebula_resource_selection::Result::exception)
    return{Phase::Failed,reason?reason:"resource_managed_exception"};
  if(dispatched!=nebula_resource_selection::Result::dispatched)
    return{Phase::Failed,reason?reason:"resource_callback_guard"};
  action_=action;binding_=observation.binding;before_generation_=observation.resource_generation;
  deadline_=deadline;phase_=Phase::Awaiting;code_="resource_callback_started";
  return{phase_,code_};
}
Result Module::poll(Host&host,std::uint64_t now) noexcept {
  if(phase_!=Phase::Awaiting)return{Phase::Failed,"resource_not_pending"};
  if(now>=deadline_){phase_=Phase::Failed;code_="resource_deadline";return{phase_,code_};}
  Observation observation{};nebula_resource_selection::Snapshot transient{};const char*reason=nullptr;
  if(!host.capture(action_,false,observation,transient,reason)){
    phase_=Phase::Failed;code_=reason?reason:"resource_capture_guard";return{phase_,code_};
  }
  if(!same(binding_,observation.binding)){
    phase_=Phase::Failed;code_="resource_operation_binding_changed";return{phase_,code_};
  }
  const bool expected=remove(action_)?observation.current_empty:observation.current_exact;
  if(observation.resource_generation>before_generation_&&expected){
    phase_=Phase::Complete;code_="resource_selection_complete";return{phase_,code_};
  }
  code_="resource_selection_pending";return{phase_,code_};
}
}
