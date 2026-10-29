#include "automation_store.h"
#include <cassert>
#include <cstring>
#include <vector>

using namespace nac_store;

static Context ready_context(){
    return {true,true,true,true,true,true,true,true,true,true,true,true,true,true,true,true};
}
static RowScan unique_rows(){return {true,true,true,1,1,1,1};}

struct FakeHost final:Host {
    Observation value{};std::vector<Callback> calls{};InvokeResult result{InvokeResult::Started};
    bool suppress_generation_edge{};
    bool capture(Observation &out,const char *&) noexcept override{out=value;return true;}
    InvokeResult invoke(Callback callback,const char *&reason) noexcept override{
        calls.push_back(callback);if(result!=InvokeResult::Started){reason="fake_invoke_failure";return result;}
        switch(callback){
        case Callback::OpenShop:value.shop_closed=false;value.shop_open=true;value.event_active=true;
            value.shop_object_active=true;value.clothing_selected=true;value.input_enabled=false;break;
        case Callback::Clothing:value.current_shop=true;value.shop_window_transition=true;break;
        case Callback::ShopRow:value.selected_shop=true;value.current_gender=true;
            value.gender_window_transition=!suppress_generation_edge;break;
        case Callback::FemaleRow:value.selected_female=true;value.current_type=true;
            value.type_window_transition=true;break;
        case Callback::TorsoRow:value.selected_torso=true;value.current_item=true;
            value.item_window_transition=true;break;
        case Callback::OfferRow:value.selected_offer=true;value.item_loading_active=true;break;
        case Callback::Buy:value.selected_offer=true;value.input_enabled=false;break;
        default:break;
        }
        return result;
    }
    void ready(){value.input_enabled=true;value.loading_active=false;value.item_loading_active=false;
        value.rows=unique_rows();}
};

static void pure_guards(){
    Context c=ready_context();assert(!std::strcmp(context_reason(c),"ready"));
    c.desktop_ok=false;assert(!std::strcmp(context_reason(c),"store_desktop_guard"));
    RowScan row=unique_rows();assert(!std::strcmp(row_reason(row),"ready"));
    row.complete=false;assert(!std::strcmp(row_reason(row),"store_row_scan_incomplete"));
    row=unique_rows();row.total=2;row.compatible=2;row.exact=2;row.active=2;
    assert(!std::strcmp(row_reason(row),"store_row_ambiguous"));
    row=unique_rows();row.total=2;row.exact=2;row.active=1;row.compatible=1;
    assert(!std::strcmp(row_reason(row),"store_row_ambiguous"));
    row=unique_rows();row.total=0;
    assert(!std::strcmp(row_reason(row),"store_row_count_guard"));
    OwnershipUi owned{true,true,true,true,false,false,true,false,true};
    assert(ownership(owned)==Ownership::Owned);
    OwnershipUi unowned{true,true,true,true,true,true,false,true,false};
    assert(ownership(unowned)==Ownership::Unowned);
    unowned.generation_observed=false;assert(ownership(unowned)==Ownership::Unknown);
}

static void open_and_select_chain(){
    FakeHost host;host.value.context=ready_context();host.value.shop_closed=true;host.value.input_enabled=false;
    Module module;auto r=module.dispatch(host,Action::OpenClothing,1000,false);
    assert(!std::strcmp(r.status,"started")&&host.calls.back()==Callback::OpenShop);
    r=module.dispatch(host,Action::OpenClothing,1001,false);
    assert(!std::strcmp(r.code,"store_request_limit"));
    // This is the actual V15 initial shop state: OpenShop has rendered the
    // shell, but input is disabled and no current window exists.  Clothing is
    // the original callback that creates that first asynchronous generation.
    assert(!host.value.input_enabled&&!host.value.current_shop);
    r=module.service(host,1100);
    assert(!std::strcmp(r.status,"started")&&host.calls.back()==Callback::Clothing);
    assert(!host.value.input_enabled); // later response readiness is not fabricated
    host.ready();host.value.current_shop=true;r=module.service(host,1200);
    assert(!std::strcmp(r.status,"completed")&&module.machine().phase==Phase::OpenReady);

    host.value.target_shop_row=true;host.value.rows=unique_rows();
    r=module.dispatch(host,Action::SelectFixedOffer,1300,false);
    assert(!std::strcmp(r.status,"started")&&host.calls.back()==Callback::ShopRow);
    host.ready();host.value.current_gender=true;host.value.target_female_row=true;
    r=module.service(host,1400);assert(host.calls.back()==Callback::FemaleRow);
    host.ready();host.value.current_type=true;host.value.target_torso_row=true;
    r=module.service(host,1500);assert(host.calls.back()==Callback::TorsoRow);
    host.ready();host.value.current_item=true;host.value.target_offer_row=true;
    r=module.service(host,1600);assert(host.calls.back()==Callback::OfferRow);
    host.ready();host.value.ownership={true,true,true,true,true,true,false,true,false};
    r=module.service(host,1700);
    assert(!std::strcmp(r.status,"completed")&&module.machine().phase==Phase::SelectedUnowned);
    assert(host.calls.size()==6);
}

static void purchase_gates_and_completion(){
    FakeHost host;host.value.context=ready_context();host.value.input_enabled=true;
    host.value.selected_offer=true;host.value.offer_non_bundle=true;host.value.price_canonical=true;
    host.value.price_crystals=25;host.value.price_np=10;host.value.wallet_fresh=true;host.value.wallet_crystals=100;
    host.value.ownership={true,true,true,true,true,true,false,true,false};
    Module module;auto r=module.dispatch(host,Action::BuySelectedCrystals,2000,false);
    assert(!std::strcmp(r.code,"store_purchase_disabled")&&host.calls.empty());
    r=module.dispatch(host,Action::BuySelectedCrystals,2000,true);
    assert(!std::strcmp(r.status,"started")&&host.calls.back()==Callback::Buy);
    host.ready();host.value.selected_offer=true;host.value.purchased_ui=true;host.value.wallet_fresh=true;
    host.value.wallet_crystals=75;r=module.service(host,2100);
    assert(!std::strcmp(r.status,"completed")&&module.machine().phase==Phase::BuyComplete);
}

static void failures_do_not_dispatch(){
    FakeHost host;host.value.context=ready_context();host.value.shop_open=true;host.value.current_shop=true;
    host.value.input_enabled=true;host.value.rows=unique_rows();host.value.rows.complete=false;
    Module module;auto r=module.dispatch(host,Action::SelectFixedOffer,1,false);
    assert(!std::strcmp(r.code,"store_row_scan_incomplete")&&host.calls.empty());
    FakeHost exception_host;exception_host.value.context=ready_context();exception_host.value.shop_closed=true;
    exception_host.value.input_enabled=true;exception_host.result=InvokeResult::ManagedException;
    Module exception_module;r=exception_module.dispatch(exception_host,Action::OpenClothing,1,false);
    assert(!std::strcmp(r.status,"error")&&exception_host.calls.size()==1);

    FakeHost timeout_host;timeout_host.value.context=ready_context();timeout_host.value.shop_closed=true;
    timeout_host.value.input_enabled=true;Module timeout_module;
    r=timeout_module.dispatch(timeout_host,Action::OpenClothing,10,false);
    assert(!std::strcmp(r.status,"started"));
    r=timeout_module.service(timeout_host,10+kDeadlineMs+1);
    assert(!std::strcmp(r.code,"store_generation_timeout"));

    OwnershipUi contradictory{true,true,true,true,true,true,true,true,true};
    assert(ownership(contradictory)==Ownership::Unknown);

    // A manager selection alone is not a generation edge.  The original row
    // callback must also produce its source-backed window transition.
    FakeHost stale;stale.value.context=ready_context();stale.value.shop_open=true;
    stale.value.current_shop=true;stale.value.input_enabled=true;stale.value.rows=unique_rows();
    stale.value.target_shop_row=true;stale.value.selected_shop=true;stale.suppress_generation_edge=true;
    Module stale_module;
    auto stale_result=stale_module.dispatch(stale,Action::SelectFixedOffer,5,false);
    assert(!std::strcmp(stale_result.status,"error"));
    assert(!std::strcmp(stale_result.code,"store_shop_callback_not_accepted"));
    auto stale_retry=stale_module.dispatch(stale,Action::SelectFixedOffer,6,false);
    assert(!std::strcmp(stale_retry.code,"store_request_limit"));
    assert(stale.calls.size()==1);
}

int main(){pure_guards();open_and_select_chain();purchase_gates_and_completion();failures_do_not_dispatch();}
