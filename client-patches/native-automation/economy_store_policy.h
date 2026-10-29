#pragma once
#include <cstdint>
#include <cstring>

namespace nebula_economy {

constexpr std::uint64_t kDeadlineMs=120000;
constexpr unsigned kMaxRows=256;

enum class Route : std::uint8_t { WardrobeFemaleTorso, Companion, Locomotion };
enum class Currency : std::uint8_t { Crystals, NP };
enum class Action : std::uint8_t { Open, SelectWardrobe, SelectCompanion, SelectLocomotion, BuyCrystals, BuyNP };
enum class Callback : std::uint8_t { None, OpenShop, Clothing, ShopRow, GenderRow, TypeRow, OfferRow, Buy, Companions, Locomotions };
enum class Phase : std::uint8_t { Idle,OpenWait,ClothingWait,OpenReady,ShopWait,GenderWait,TypeWait,OfferWait,SelectedUnowned,SelectedOwned,BuyWait,BuyComplete,Denied,Failed,CatalogWait };
enum class Decision : std::uint8_t { Wait,Invoke,Complete,Fail };
enum class Ownership : std::uint8_t { Unknown,Unowned,Owned };

struct Fixture {
    Route route; const char *shop_id; int gender_id; const char *type_id;
    const char *offer_id; const char *item_id; int crystals; int np; bool direct_items;
};

inline const Fixture &fixture(Route route) {
    static constexpr Fixture rows[]={
        {Route::WardrobeFemaleTorso,"local-preservation-clothing",1,"CLOTH_BODY_TORSO","local-clothing-female-5","A1oWEkEcr2T38NeXd3Yc32b676jmy0Vo",25,10,false},
        {Route::Companion,"local-preservation-companions",3,"items","local-companion-1","A0IQgRXmw2UMG8T5UGrVE022o7Id25GU",40,20,true},
        {Route::Locomotion,"local-preservation-locomotions",6,"items","local-locomotion-1","AJ7C1vNaTXDE2G5xRD5Uq4Tqv22a775K",35,15,true},
    };
    return rows[static_cast<unsigned>(route)];
}

struct Context {
    bool desktop_ok{},scene_nexus{},identity_current{},manager_current{},in_space{};
    bool network_connected{},network_authenticated{},network_ready{},connection_ready{};
    bool local_player_alive{},local_player_done{},not_travelling{},session_same{},shop_bound{},no_overlap{};
};
inline const char *context_reason(const Context&s) {
    if(!s.desktop_ok)return "economy_desktop_guard";
    if(!s.scene_nexus||!s.identity_current||!s.manager_current||!s.in_space)return "economy_context_guard";
    if(!s.network_connected||!s.network_authenticated||!s.network_ready||!s.connection_ready||!s.local_player_alive||!s.local_player_done||!s.not_travelling)return "economy_network_not_ready";
    if(!s.session_same||!s.shop_bound)return "economy_binding_guard";
    if(!s.no_overlap)return "economy_action_overlap";
    return "ready";
}

struct RowAuthority { bool complete{},list_valid{},current_window{}; unsigned total{},exact{},active{},compatible{}; };
inline const char *row_reason(const RowAuthority&s) {
    if(!s.current_window)return "economy_window_changed";
    if(!s.list_valid||!s.complete)return "economy_row_scan_incomplete";
    if(s.total>kMaxRows||s.exact>s.total||s.active>s.exact||s.compatible>s.active)return "economy_row_count_guard";
    if(s.exact!=1||s.active!=1||s.compatible!=1)return s.exact?"economy_row_ambiguous":"economy_row_missing";
    return "ready";
}

struct Observation {
    Context context{}; RowAuthority row{};
    bool shop_closed{},shop_open{},event_active{},shop_object_active{},clothing_selected{};
    bool input_enabled{},loading_active{},current_shop{},current_gender{},current_type{},current_item{};
    bool window_transition{},target_row{},selected_fixture{},selected_offer{},item_loading_active{};
    // Exact original OfferRow edge, or the same deadline-bounded OfferWait.
    // Observation only: never an ownership or purchase authorization.
    bool offer_transition_bound{};
    bool selected_shop{},selected_gender{},selected_type{};
    bool ownership_generation{},buy_active{},buy_np_active{},label_buy{},label_purchased{},gift_selected{};
    bool offer_non_bundle{},price_canonical{},wallet_fresh{};
    int price_crystals{},price_np{},wallet_crystals{},wallet_np{};
    // The original receiver has no durable response-token field.  Completion
    // is therefore derived only after the callback-specific busy edge, input
    // re-enable, wallet refresh and ownership refresh have all completed.
    bool purchase_cycle_complete{};
};

inline Ownership ownership(const Observation&o) {
    if(!o.ownership_generation||!o.input_enabled||o.loading_active||!o.selected_offer)return Ownership::Unknown;
    if(!o.buy_active&&!o.buy_np_active&&o.gift_selected&&o.label_purchased)return Ownership::Owned;
    if(o.buy_active&&o.label_buy&&!o.label_purchased)return Ownership::Unowned;
    return Ownership::Unknown;
}

struct Machine {
    Phase phase{Phase::Idle}; Route route{Route::WardrobeFemaleTorso}; Currency currency{Currency::Crystals};
    std::uint64_t deadline{}; bool edge_seen{},purchase_started_unowned{};
    int wallet_before{},other_before{}; const char *status{"idle"};
};
inline bool offer_wait_authorized(const Machine&m,std::uint64_t now) noexcept {
    return m.phase==Phase::OfferWait&&m.edge_seen&&m.deadline&&now<=m.deadline;
}
struct Step { Decision decision; Callback callback; const char *reason; };
inline Step fail(Machine&m,const char*r){m.phase=Phase::Failed;m.status=r;return{Decision::Fail,Callback::None,r};}

inline Step begin_open(Machine&m,const Observation&o,std::uint64_t now) {
    auto c=context_reason(o.context);if(std::strcmp(c,"ready"))return fail(m,c);
    if(!o.shop_closed)return fail(m,"economy_shop_already_open");
    m={};m.phase=Phase::OpenWait;m.deadline=now+kDeadlineMs;m.status="economy_open_dispatch";
    return{Decision::Invoke,Callback::OpenShop,m.status};
}
inline Step begin_select(Machine&m,Route route,const Observation&o,std::uint64_t now) {
    auto c=context_reason(o.context);if(std::strcmp(c,"ready"))return fail(m,c);
    if(m.phase!=Phase::OpenReady||!o.shop_open||!o.current_shop||!o.input_enabled||o.loading_active)return fail(m,"economy_catalog_not_ready");
    if(route!=m.route){
        if(!o.row.current_window||!o.row.complete||!o.row.list_valid||o.row.total>kMaxRows||o.row.exact>o.row.total||o.row.active>o.row.exact||o.row.compatible>o.row.active)return fail(m,"economy_row_scan_incomplete");
        m.route=route;m.phase=Phase::CatalogWait;m.edge_seen=false;m.deadline=now+kDeadlineMs;m.status="economy_top_catalog_dispatch";
        return{Decision::Invoke,route==Route::Companion?Callback::Companions:route==Route::Locomotion?Callback::Locomotions:Callback::Clothing,m.status};
    }
    auto r=row_reason(o.row);if(std::strcmp(r,"ready")||!o.target_row)return fail(m,std::strcmp(r,"ready")?r:"economy_shop_identity_mismatch");
    m.route=route;m.phase=Phase::ShopWait;m.edge_seen=false;m.deadline=now+kDeadlineMs;m.status="economy_shop_dispatch";
    return{Decision::Invoke,Callback::ShopRow,m.status};
}
inline Step begin_buy(Machine&m,Currency currency,const Observation&o,std::uint64_t now,bool opt_in) {
    auto c=context_reason(o.context);if(std::strcmp(c,"ready"))return fail(m,c);
    const auto&f=fixture(m.route);auto own=ownership(o);
    if(!opt_in)return fail(m,"economy_purchase_disabled");
    if(m.phase!=Phase::SelectedUnowned||own!=Ownership::Unowned)return fail(m,own==Ownership::Owned?"economy_duplicate_owned":"economy_ownership_unknown");
    if(!o.offer_non_bundle||!o.price_canonical||o.price_crystals!=f.crystals||o.price_np!=f.np||!o.wallet_fresh)return fail(m,"economy_price_or_wallet_guard");
    m.currency=currency;m.wallet_before=currency==Currency::Crystals?o.wallet_crystals:o.wallet_np;
    m.other_before=currency==Currency::Crystals?o.wallet_np:o.wallet_crystals;
    m.purchase_started_unowned=true;
    m.phase=Phase::BuyWait;m.edge_seen=false;m.deadline=now+kDeadlineMs;m.status=currency==Currency::Crystals?"economy_buy_crystals_dispatch":"economy_buy_np_dispatch";
    return{Decision::Invoke,Callback::Buy,m.status};
}

inline Step pump(Machine&m,const Observation&o,std::uint64_t now) {
    if(now>m.deadline)return fail(m,"economy_generation_timeout");
    auto c=context_reason(o.context);if(std::strcmp(c,"ready"))return fail(m,c);
    // V16 closure: OpenShop creates the shell with input disabled/current window
    // unset. Invoke original OnClickClothing from its exact generation edge.
    if(m.phase==Phase::OpenWait){
        if(!m.edge_seen)return{Decision::Wait,Callback::None,"economy_open_generation_missing"};
        if(!o.shop_open||!o.event_active||!o.shop_object_active||!o.clothing_selected)return{Decision::Wait,Callback::None,"economy_open_pending"};
        m.phase=Phase::ClothingWait;m.edge_seen=false;return{Decision::Invoke,Callback::Clothing,"economy_clothing_dispatch"};
    }
    if(!o.input_enabled||o.loading_active)m.edge_seen=true;
    if(!m.edge_seen)return{Decision::Wait,Callback::None,"economy_generation_missing"};
    if(!o.input_enabled||o.loading_active)return{Decision::Wait,Callback::None,"economy_generation_pending"};
    auto row=row_reason(o.row);const auto&f=fixture(m.route);
    switch(m.phase){
    case Phase::CatalogWait:
        if(!o.current_shop||std::strcmp(row,"ready")||!o.target_row)return{Decision::Wait,Callback::None,"economy_top_catalog_pending"};
        m.phase=Phase::ShopWait;m.edge_seen=false;return{Decision::Invoke,Callback::ShopRow,"economy_shop_dispatch"};
    case Phase::ClothingWait:
        if(!o.current_shop||std::strcmp(row,"ready"))return{Decision::Wait,Callback::None,"economy_catalog_pending"};
        m.phase=Phase::OpenReady;m.status="economy_catalog_ready";return{Decision::Complete,Callback::None,m.status};
    case Phase::ShopWait:
        if(!o.current_gender||!o.selected_shop||std::strcmp(row,"ready")||!o.target_row)return{Decision::Wait,Callback::None,"economy_gender_pending"};
        m.phase=Phase::GenderWait;m.edge_seen=false;return{Decision::Invoke,Callback::GenderRow,"economy_gender_dispatch"};
    case Phase::GenderWait:
        if(f.direct_items){
            if(!o.current_item||!o.selected_shop||!o.selected_gender||std::strcmp(row,"ready")||!o.target_row)return{Decision::Wait,Callback::None,"economy_direct_offer_pending"};
            m.phase=Phase::OfferWait;m.edge_seen=false;return{Decision::Invoke,Callback::OfferRow,"economy_offer_dispatch"};
        }
        if(!o.current_type||!o.selected_shop||!o.selected_gender||std::strcmp(row,"ready")||!o.target_row)return{Decision::Wait,Callback::None,"economy_type_pending"};
        m.phase=Phase::TypeWait;m.edge_seen=false;return{Decision::Invoke,Callback::TypeRow,"economy_type_dispatch"};
    case Phase::TypeWait:
        if(!o.current_item||!o.selected_fixture||std::strcmp(row,"ready")||!o.target_row)return{Decision::Wait,Callback::None,"economy_offer_pending"};
        m.phase=Phase::OfferWait;m.edge_seen=false;return{Decision::Invoke,Callback::OfferRow,"economy_offer_dispatch"};
    case Phase::OfferWait:{
        auto own=ownership(o);if(own==Ownership::Unknown)return{Decision::Wait,Callback::None,"economy_ownership_pending"};
        m.phase=own==Ownership::Owned?Phase::SelectedOwned:Phase::SelectedUnowned;
        m.status=own==Ownership::Owned?"economy_offer_owned":"economy_offer_unowned";return{Decision::Complete,Callback::None,m.status};}
    case Phase::BuyWait:{
        if(!o.purchase_cycle_complete)return{Decision::Wait,Callback::None,"economy_purchase_pending"};
        int selected=m.currency==Currency::Crystals?o.wallet_crystals:o.wallet_np;
        int other=m.currency==Currency::Crystals?o.wallet_np:o.wallet_crystals;
        int price=m.currency==Currency::Crystals?f.crystals:f.np;
        if(!o.wallet_fresh||other!=m.other_before)return fail(m,"economy_purchase_wallet_changed");
        auto own=ownership(o);
        if(selected==m.wallet_before&&own==Ownership::Unowned&&m.wallet_before<price){
            const char*t=m.currency==Currency::Crystals?"economy_insufficient_crystals":"economy_insufficient_np";
            m.phase=Phase::Denied;m.status=t;return{Decision::Complete,Callback::None,t};
        }
        if(selected==m.wallet_before){
            // The native receiver retains no raw response token.  An affordable
            // unchanged/unowned result can be HTTP/auth/network failure, while
            // an unowned-to-owned transition without debit can be a concurrent
            // admin grant. Neither is attributed to NO* or ISPURCHASED.
            return fail(m,own==Ownership::Owned?
                "economy_owned_without_debit_unattributed":
                "economy_affordable_unchanged_unattributed");
        }
        if(selected!=m.wallet_before-price||own!=Ownership::Owned)return fail(m,"economy_purchase_completion_mismatch");
        m.phase=Phase::BuyComplete;m.status="economy_purchase_complete";return{Decision::Complete,Callback::None,m.status};}
    default:return fail(m,"economy_phase_guard");
    }
}

} // namespace nebula_economy
