#include "resource_navigation_module.h"
namespace nebula_resource_navigation {
namespace { bool same(const Binding&a,const Binding&b) noexcept{return a.valid&&b.valid&&a.session_hash==b.session_hash&&a.local_guid_hash==b.local_guid_hash&&a.scene_hash==b.scene_hash&&a.generation_epoch==b.generation_epoch&&a.local_net_id==b.local_net_id&&a.manager_instance_id==b.manager_instance_id;} }
void Module::reset() noexcept {action_=Action::PrepareCompanionSelect;phase_=Phase::Idle;binding_={};deadline_=0;code_="idle";}
Result Module::begin(Host&h,Action a,std::uint64_t now,std::uint64_t deadline) noexcept {
 if(pending())return{Phase::Failed,"resource_navigation_overlap"};
 reset();
 if(deadline<=now)return{Phase::Failed,"resource_navigation_deadline_guard"};
 Observation o{};const char*r=nullptr;if(!h.capture(a,o,r)||!o.binding.valid)return{Phase::Failed,r?r:"resource_navigation_capture_guard"};
 action_=a;binding_=o.binding;deadline_=deadline;
 if(!o.root_visible){if(!h.open_root(a,r))return{Phase::Failed,r?r:"resource_navigation_root_open_guard"};phase_=Phase::AwaitRoot;code_="resource_navigation_root_open_started";}
 else if(!o.wheel_visible){if(!h.open_panel(a,r))return{Phase::Failed,r?r:"resource_navigation_panel_open_guard"};phase_=Phase::AwaitWheel;code_="resource_navigation_panel_open_started";}
 else {if(!h.select(a,r))return{Phase::Failed,r?r:"resource_navigation_select_guard"};phase_=Phase::AwaitSelection;code_="resource_navigation_selection_started";}
 return{phase_,code_};
}
Result Module::poll(Host&h,std::uint64_t now) noexcept {
 if(!pending())return{Phase::Failed,"resource_navigation_not_pending"};
 if(now>=deadline_){phase_=Phase::Failed;code_="resource_navigation_deadline";return{phase_,code_};}
 Observation o{};const char*r=nullptr;if(!h.capture(action_,o,r)){phase_=Phase::Failed;code_=r?r:"resource_navigation_capture_guard";return{phase_,code_};}
 if(!same(binding_,o.binding)){phase_=Phase::Failed;code_="resource_navigation_binding_changed";return{phase_,code_};}
 if(phase_==Phase::AwaitRoot){if(!o.root_visible){code_="resource_navigation_root_pending";return{phase_,code_};}if(!h.open_panel(action_,r)){phase_=Phase::Failed;code_=r?r:"resource_navigation_panel_open_guard";return{phase_,code_};}phase_=Phase::AwaitWheel;code_="resource_navigation_panel_open_started";return{phase_,code_};}
 if(phase_==Phase::AwaitWheel){if(!o.wheel_visible){code_="resource_navigation_wheel_pending";return{phase_,code_};}if(!h.select(action_,r)){phase_=Phase::Failed;code_=r?r:"resource_navigation_select_guard";return{phase_,code_};}phase_=Phase::AwaitSelection;code_="resource_navigation_selection_started";return{phase_,code_};}
 if(o.root_visible&&o.wheel_visible&&o.target_selected&&o.target_ready){phase_=Phase::Complete;code_="resource_navigation_complete";return{phase_,code_};}
 code_="resource_navigation_selection_pending";return{phase_,code_};
}
}
