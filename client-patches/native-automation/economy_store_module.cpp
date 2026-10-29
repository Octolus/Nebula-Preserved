#include "economy_store_module.h"
#include <cstring>

namespace nebula_economy {
bool Module::accepted(Callback cb,const Observation&o,const char*&reason) noexcept {
    if(std::strcmp(context_reason(o.context),"ready")){reason="economy_context_lost_after_callback";return false;}
    bool ok=false;
    switch(cb){
    case Callback::OpenShop:ok=machine_.phase==Phase::OpenWait&&o.shop_open&&o.event_active&&o.shop_object_active&&o.clothing_selected;break;
    case Callback::Clothing:ok=o.current_shop&&((machine_.phase==Phase::ClothingWait&&o.window_transition)||(machine_.phase==Phase::CatalogWait&&(o.loading_active||!o.input_enabled)));break;
    case Callback::Companions:
    case Callback::Locomotions:ok=machine_.phase==Phase::CatalogWait&&o.current_shop&&(o.loading_active||!o.input_enabled);break;
    case Callback::ShopRow:ok=machine_.phase==Phase::ShopWait&&o.selected_shop&&(o.loading_active||!o.input_enabled||(o.current_gender&&o.window_transition));break;
    case Callback::GenderRow:ok=machine_.phase==Phase::GenderWait&&o.selected_shop&&o.selected_gender&&(o.loading_active||!o.input_enabled||((fixture(machine_.route).direct_items?o.current_item:o.current_type)&&o.window_transition));break;
    case Callback::TypeRow:ok=machine_.phase==Phase::TypeWait&&o.selected_fixture&&(o.loading_active||!o.input_enabled||(o.current_item&&o.window_transition));break;
    case Callback::OfferRow:ok=machine_.phase==Phase::OfferWait&&o.selected_fixture&&o.selected_offer&&(o.item_loading_active||o.offer_transition_bound);break;
    case Callback::Buy:ok=machine_.phase==Phase::BuyWait&&o.selected_fixture&&o.selected_offer&&!o.input_enabled;break;
    default:break;
    }
    if(!ok)reason="economy_callback_generation_missing";
    return ok;
}
Result Module::execute(Host&host,Step step) noexcept {
    if(step.decision==Decision::Fail)return{"rejected",step.reason};
    if(step.decision==Decision::Wait)return{"pending",step.reason};
    if(step.decision==Decision::Complete)return{"completed",step.reason};
    const char*reason=nullptr;auto result=host.invoke(machine_.route,machine_.currency,step.callback,reason);
    if(result!=InvokeResult::Started){machine_.phase=Phase::Failed;machine_.status=reason?reason:"economy_invoke_failed";return{result==InvokeResult::ManagedException?"error":"rejected",machine_.status};}
    Observation after{};
    if(!host.capture(machine_.route,after,reason)||!accepted(step.callback,after,reason)){machine_.phase=Phase::Failed;machine_.status=reason?reason:"economy_post_callback_probe";return{"error",machine_.status};}
    machine_.edge_seen=true;machine_.status=step.reason;return{"started",step.reason};
}
Result Module::dispatch(Host&host,Action action,std::uint64_t now,bool opt_in) noexcept {
    auto i=static_cast<unsigned>(action);if(i>=6||attempts_[i])return{"rejected","economy_request_limit"};
    Route capture_route=machine_.route;
    if(action==Action::SelectWardrobe)capture_route=Route::WardrobeFemaleTorso;
    else if(action==Action::SelectCompanion)capture_route=Route::Companion;
    else if(action==Action::SelectLocomotion)capture_route=Route::Locomotion;
    Observation o{};const char*reason=nullptr;if(!host.capture(capture_route,o,reason))return{"rejected",reason?reason:"economy_probe_failed"};
    Step step{Decision::Fail,Callback::None,"economy_action_guard"};
    if(action==Action::Open)step=begin_open(machine_,o,now);
    else if(action==Action::SelectWardrobe)step=begin_select(machine_,Route::WardrobeFemaleTorso,o,now);
    else if(action==Action::SelectCompanion)step=begin_select(machine_,Route::Companion,o,now);
    else if(action==Action::SelectLocomotion)step=begin_select(machine_,Route::Locomotion,o,now);
    else step=begin_buy(machine_,action==Action::BuyNP?Currency::NP:Currency::Crystals,o,now,opt_in);
    if(step.decision==Decision::Invoke)++attempts_[i];
    return execute(host,step);
}
Result Module::service(Host&host,std::uint64_t now) noexcept {
    Observation o{};const char*reason=nullptr;if(!host.capture(machine_.route,o,reason)){machine_.phase=Phase::Failed;machine_.status=reason?reason:"economy_probe_failed";return{"error",machine_.status};}
    return execute(host,pump(machine_,o,now));
}
}
