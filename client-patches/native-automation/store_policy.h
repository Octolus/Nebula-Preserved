#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace nac_store {

constexpr unsigned kMaxRows = 256;
constexpr unsigned kMaxReportedRows = 32;
constexpr unsigned kMaxIdentityBytes = 64;
constexpr std::uint64_t kDeadlineMs = 120000;

enum class Action : std::uint8_t { OpenClothing, SelectFixedOffer, BuySelectedCrystals };
enum class Callback : std::uint8_t {
    None, OpenShop, Clothing, ShopRow, FemaleRow, TorsoRow, OfferRow, Buy
};
enum class Phase : std::uint8_t {
    Idle, OpenWait, ClothingWait, OpenReady, ShopWait, GenderWait, TypeWait, OfferWait,
    SelectedUnowned, SelectedOwned, BuyWait, BuyComplete, Failed
};
enum class Ownership : std::uint8_t { Unknown, Unowned, Owned };
enum class Decision : std::uint8_t { Wait, Invoke, Complete, Fail };

struct Context {
    bool desktop_ok{}, scene_nexus{}, ps4_current{}, manager_current{};
    bool in_space{}, network_connected{}, network_authenticated{}, network_ready{};
    bool connection_ready{}, local_player_alive{}, local_player_done{}, not_travelling{};
    bool session_same{}, managers_same{}, shop_net{}, no_overlap{};
};

inline const char *context_reason(const Context &s) {
    if(!s.desktop_ok)return "store_desktop_guard";
    if(!s.scene_nexus)return "store_wrong_scene";
    if(!s.ps4_current||!s.manager_current)return "store_root_guard";
    if(!s.in_space)return "store_not_in_space";
    if(!s.network_connected||!s.network_authenticated||!s.network_ready||
       !s.connection_ready||!s.local_player_alive||!s.local_player_done||!s.not_travelling)
        return "store_network_not_ready";
    if(!s.session_same)return "store_session_changed";
    if(!s.managers_same||!s.shop_net)return "store_manager_binding";
    if(!s.no_overlap)return "store_action_overlap";
    return "ready";
}

struct RowScan {
    bool complete{}, current_window{}, list_valid{};
    unsigned total{}, exact{}, active{}, compatible{};
};
inline const char *row_reason(const RowScan &s) {
    if(!s.current_window)return "store_window_changed";
    if(!s.list_valid)return "store_row_list_guard";
    if(!s.complete)return "store_row_scan_incomplete";
    if(s.total>kMaxRows)return "store_row_bound";
    if(s.exact>s.total||s.active>s.exact||s.compatible>s.active)return "store_row_count_guard";
    if(!s.exact)return "store_row_missing";
    // Complete-scan authority is unique at every narrowing layer.  An inactive
    // duplicate with the same exact shipped identity is not ignored merely
    // because only one row is currently callback-compatible.
    if(s.exact!=1)return "store_row_ambiguous";
    if(!s.active)return "store_row_inactive";
    if(s.active!=1||s.compatible!=1)return "store_row_ambiguous";
    return "ready";
}

struct OwnershipUi {
    bool generation_observed{}, input_enabled{}, loading_inactive{}, selected_offer_exact{};
    bool buy_active{}, buy_np_active{}, gift_selected{};
    bool label_buy{}, label_purchased{};
};
inline Ownership ownership(const OwnershipUi &s) {
    if(!s.generation_observed||!s.input_enabled||!s.loading_inactive||!s.selected_offer_exact)
        return Ownership::Unknown;
    if(!s.buy_active&&!s.buy_np_active&&s.gift_selected&&s.label_purchased)
        return Ownership::Owned;
    if(s.buy_active&&s.label_buy&&!s.label_purchased)
        return Ownership::Unowned;
    return Ownership::Unknown;
}

struct PurchasePrecondition {
    Context context{};Ownership owned{Ownership::Unknown};
    bool opt_in{}, fixed_offer{}, non_bundle{}, price_canonical{}, wallet_fresh{};
    int crystals_price{}, np_price{}, wallet_crystals{};
};
inline const char *purchase_reason(const PurchasePrecondition &s) {
    const char *context=context_reason(s.context);if(std::strcmp(context,"ready"))return context;
    if(!s.opt_in)return "store_purchase_disabled";
    if(!s.fixed_offer||!s.non_bundle)return "store_offer_guard";
    if(s.owned!=Ownership::Unowned)return s.owned==Ownership::Owned?"store_offer_owned":"store_ownership_unknown";
    if(!s.price_canonical||s.crystals_price!=25||s.np_price!=10)return "store_price_mismatch";
    if(!s.wallet_fresh||s.wallet_crystals<25)return "store_wallet_precondition";
    return "ready";
}

struct PurchaseCompletion {
    bool busy_observed{}, ready{}, selected_offer_exact{}, purchased_ui{};
    bool wallet_refreshed{};int before{}, after{}, price{};
};
inline const char *purchase_completion_reason(const PurchaseCompletion &s) {
    if(!s.busy_observed)return "store_purchase_generation_missing";
    if(!s.ready)return "store_purchase_pending";
    if(!s.selected_offer_exact)return "store_offer_changed";
    if(!s.purchased_ui)return "store_purchase_ui_failure";
    if(!s.wallet_refreshed||s.price!=25||s.after!=s.before-s.price)return "store_wallet_mismatch";
    return "ready";
}

struct Observation {
    Context context{};
    bool shop_closed{}, shop_open{}, input_enabled{}, loading_active{};
    bool event_active{}, shop_object_active{}, clothing_selected{};
    bool current_shop{},current_gender{},current_type{},current_item{},current_wardrobe{};
    // Callback-specific, adapter-derived generation markers.  These are sampled
    // immediately after the original callback and are never inferred from a
    // later manager state.
    bool shop_window_transition{},gender_window_transition{},type_window_transition{};
    bool item_window_transition{},item_loading_active{};
    RowScan rows{};
    bool target_shop_row{},target_female_row{},target_torso_row{},target_offer_row{};
    bool selected_shop{},selected_female{},selected_torso{},selected_offer{};
    bool offer_non_bundle{},price_canonical{},wallet_fresh{};
    int price_crystals{},price_np{},wallet_crystals{};
    OwnershipUi ownership{};
    bool purchased_ui{};
};

struct Machine {
    Phase phase{Phase::Idle};Action action{Action::OpenClothing};
    bool busy_seen{};std::uint64_t deadline{};int wallet_before{};
    const char *status="idle";
};

struct Step {Decision decision{Decision::Wait};Callback callback{Callback::None};const char *reason="pending";};

inline Step fail(Machine &m,const char *reason){m.phase=Phase::Failed;m.status=reason;return {Decision::Fail,Callback::None,reason};}

inline Step begin(Machine &m,Action action,const Observation &o,std::uint64_t now,bool purchase_opt_in) {
    const char *ctx=context_reason(o.context);if(std::strcmp(ctx,"ready"))return fail(m,ctx);
    m.action=action;m.deadline=now+kDeadlineMs;m.busy_seen=false;
    if(action==Action::OpenClothing) {
        if(!o.shop_closed)return fail(m,"store_already_open");
        m.phase=Phase::OpenWait;m.status="store_open_dispatch";
        return {Decision::Invoke,Callback::OpenShop,"store_open_dispatch"};
    }
    if(action==Action::SelectFixedOffer) {
        if(!o.shop_open||!o.current_shop||!o.input_enabled)return fail(m,"store_clothing_not_ready");
        const char *row=row_reason(o.rows);if(std::strcmp(row,"ready")||!o.target_shop_row)return fail(m,std::strcmp(row,"ready")?row:"store_shop_row_mismatch");
        m.phase=Phase::ShopWait;m.status="store_shop_dispatch";
        return {Decision::Invoke,Callback::ShopRow,"store_shop_dispatch"};
    }
    PurchasePrecondition p{o.context,ownership(o.ownership),purchase_opt_in,o.selected_offer,o.offer_non_bundle,
                           o.price_canonical,o.wallet_fresh,o.price_crystals,o.price_np,o.wallet_crystals};
    const char *reason=purchase_reason(p);if(std::strcmp(reason,"ready"))return fail(m,reason);
    m.wallet_before=o.wallet_crystals;m.phase=Phase::BuyWait;m.status="store_buy_dispatch";
    return {Decision::Invoke,Callback::Buy,"store_buy_dispatch"};
}

inline Step pump(Machine &m,const Observation &o,std::uint64_t now) {
    if(m.phase==Phase::Idle||m.phase==Phase::OpenReady||m.phase==Phase::SelectedUnowned||
       m.phase==Phase::SelectedOwned||m.phase==Phase::BuyComplete||m.phase==Phase::Failed)
        return {Decision::Wait,Callback::None,m.status};
    if(now>m.deadline)return fail(m,"store_generation_timeout");
    const char *ctx=context_reason(o.context);if(std::strcmp(ctx,"ready"))return fail(m,ctx);
    // OpenShop deliberately leaves ShopManager input disabled and no current
    // base window.  The shipped OnClickClothing callback is the operation that
    // activates clothingWindow, assigns currentBaseWindow and starts the first
    // data request.  Therefore this one transition is authorized by the
    // callback-specific OpenShop generation edge, not by the later response-
    // readiness gate.  Every later phase still waits for input enabled and
    // loading inactive before inspecting or invoking a rendered row.
    if(m.phase==Phase::OpenWait) {
        if(!m.busy_seen)return {Decision::Wait,Callback::None,"store_open_generation_missing"};
        if(!o.shop_open||!o.event_active||!o.shop_object_active||!o.clothing_selected)
            return {Decision::Wait,Callback::None,"store_open_pending"};
        m.phase=Phase::ClothingWait;m.busy_seen=false;m.status="store_clothing_dispatch";
        return {Decision::Invoke,Callback::Clothing,m.status};
    }
    if(!o.input_enabled||o.loading_active)m.busy_seen=true;
    if(!m.busy_seen)return {Decision::Wait,Callback::None,"store_busy_not_seen"};
    if(!o.input_enabled||o.loading_active)return {Decision::Wait,Callback::None,"store_generation_pending"};
    const char *row=row_reason(o.rows);
    switch(m.phase) {
    case Phase::ClothingWait:
        if(!o.shop_open||!o.event_active||!o.shop_object_active)return fail(m,"store_open_state_mismatch");
        if(!o.current_shop||std::strcmp(row,"ready"))return {Decision::Wait,Callback::None,"store_clothing_pending"};
        m.phase=Phase::OpenReady;m.status="store_clothing_ready";return {Decision::Complete,Callback::None,m.status};
    case Phase::ShopWait:
        if(!o.current_gender||!o.selected_shop||std::strcmp(row,"ready")||!o.target_female_row)return {Decision::Wait,Callback::None,"store_gender_pending"};
        m.phase=Phase::GenderWait;m.busy_seen=false;m.status="store_female_dispatch";
        return {Decision::Invoke,Callback::FemaleRow,m.status};
    case Phase::GenderWait:
        if(!o.current_type||!o.selected_female||std::strcmp(row,"ready")||!o.target_torso_row)return {Decision::Wait,Callback::None,"store_type_pending"};
        m.phase=Phase::TypeWait;m.busy_seen=false;m.status="store_torso_dispatch";
        return {Decision::Invoke,Callback::TorsoRow,m.status};
    case Phase::TypeWait:
        if(!o.current_item||!o.selected_torso||std::strcmp(row,"ready")||!o.target_offer_row)return {Decision::Wait,Callback::None,"store_offer_pending"};
        m.phase=Phase::OfferWait;m.busy_seen=false;m.status="store_offer_dispatch";
        return {Decision::Invoke,Callback::OfferRow,m.status};
    case Phase::OfferWait: {
        auto own=ownership(o.ownership);
        if(own==Ownership::Unknown)return {Decision::Wait,Callback::None,"store_ownership_pending"};
        m.phase=own==Ownership::Owned?Phase::SelectedOwned:Phase::SelectedUnowned;
        m.status=own==Ownership::Owned?"store_offer_owned":"store_offer_unowned";
        return {Decision::Complete,Callback::None,m.status};
    }
    case Phase::BuyWait: {
        PurchaseCompletion c{m.busy_seen,true,o.selected_offer,o.purchased_ui,o.wallet_fresh,
                             m.wallet_before,o.wallet_crystals,25};
        const char *reason=purchase_completion_reason(c);if(std::strcmp(reason,"ready"))return fail(m,reason);
        m.phase=Phase::BuyComplete;m.status="store_buy_native_complete";
        return {Decision::Complete,Callback::None,m.status};
    }
    default:return fail(m,"store_phase_guard");
    }
}

}
