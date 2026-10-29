#include "automation_store.h"
#include <cstring>

namespace nac_store {

bool Module::accepted(Callback callback,const Observation &after,const char *&reason) noexcept {
    if(std::strcmp(context_reason(after.context),"ready")){reason="store_context_lost_after_dispatch";return false;}
    switch(callback) {
    case Callback::OpenShop:
        if(after.shop_open&&after.event_active&&after.shop_object_active&&after.clothing_selected)return true;
        reason="store_open_callback_not_accepted";return false;
    case Callback::Clothing:
        if(after.current_shop&&after.shop_window_transition)return true;
        reason="store_clothing_callback_not_accepted";return false;
    case Callback::ShopRow:
        if(after.selected_shop&&after.current_gender&&after.gender_window_transition)return true;
        reason="store_shop_callback_not_accepted";return false;
    case Callback::FemaleRow:
        if(after.selected_female&&after.current_type&&after.type_window_transition)return true;
        reason="store_gender_callback_not_accepted";return false;
    case Callback::TorsoRow:
        if(after.selected_torso&&after.current_item&&after.item_window_transition)return true;
        reason="store_type_callback_not_accepted";return false;
    case Callback::OfferRow:
        if(after.selected_offer&&after.item_loading_active)return true;
        reason="store_offer_callback_not_accepted";return false;
    case Callback::Buy:
        if(after.selected_offer&&!after.input_enabled)return true;
        reason="store_buy_callback_not_accepted";return false;
    default:reason="store_callback_guard";return false;
    }
}

Result Module::execute(Host &host,const Step &step) noexcept {
    if(step.decision==Decision::Fail)return {"rejected",step.reason};
    if(step.decision==Decision::Wait)return {"pending",step.reason};
    if(step.decision==Decision::Complete)return {"completed",step.reason};
    const char *reason=nullptr;auto invoked=host.invoke(step.callback,reason);
    if(invoked!=InvokeResult::Started){
        machine_.phase=Phase::Failed;
        machine_.status=reason?reason:(invoked==InvokeResult::ManagedException?
            "store_managed_exception":"store_invoke_guard");
        return {invoked==InvokeResult::ManagedException?"error":"rejected",machine_.status};
    }
    Observation after{};
    if(!host.capture(after,reason)||!accepted(step.callback,after,reason)){
        machine_.phase=Phase::Failed;machine_.status=reason?reason:"store_post_dispatch_probe";
        return {"error",machine_.status};
    }
    // accepted() proves a callback-specific generation edge.  Retain only the
    // primitive fact; never retain Unity pointers or accept a later pre-existing
    // manager state as this request's generation.
    machine_.busy_seen=true;
    machine_.status=step.reason;return {"started",step.reason};
}

Result Module::dispatch(Host &host,Action action,std::uint64_t now,bool purchase_opt_in) noexcept {
    auto index=static_cast<unsigned>(action);
    if(index>=3||requests_[index])return {"rejected","store_request_limit"};
    if(machine_.phase!=Phase::Idle&&machine_.phase!=Phase::OpenReady&&
       machine_.phase!=Phase::SelectedUnowned&&machine_.phase!=Phase::SelectedOwned&&
       machine_.phase!=Phase::BuyComplete&&machine_.phase!=Phase::Failed)
        return {"rejected","store_action_overlap"};
    Observation current{};const char *reason=nullptr;
    if(!host.capture(current,reason))return {"rejected",reason?reason:"store_probe_failed"};
    auto step=begin(machine_,action,current,now,purchase_opt_in);
    // Consume the bounded action attempt before crossing the invoke boundary.
    // A managed exception or a failed immediate generation probe must never
    // make the same mutating original callback eligible for a second call.
    if(step.decision==Decision::Invoke)++requests_[index];
    return execute(host,step);
}

Result Module::service(Host &host,std::uint64_t now) noexcept {
    Observation current{};const char *reason=nullptr;
    if(!host.capture(current,reason)){
        machine_.phase=Phase::Failed;machine_.status=reason?reason:"store_probe_failed";
        return {"error",machine_.status};
    }
    return execute(host,pump(machine_,current,now));
}

}
