#include "economy_v16_adapter.h"
#include "economy_callback_generations.h"
#include <cstring>

namespace ne=nebula_economy;
namespace nebula_economy_v16 {

bool Adapter::exact_offer(ne::Route route,void *row,void *window) noexcept {
    const auto&f=ne::fixture(route);
    return core_.typed(row,"EntryItem","",true)&&core_.pointer(row,0x40)==window&&
        core_.exact_string(core_.pointer(row,0xa0),f.offer_id)&&!core_.uint8(row,0xb0);
}
bool Adapter::scan(ne::Route route,Probe&out,const char*row_class,unsigned kind) noexcept {
    auto&s=out.observation.row;s={};
    const char*window_type=kind==1?"ShopWindow":kind==2?"GenderWindow":kind==3?"ItemTypeWindow":"ItemWindow";
    if(!out.window||!core_.typed(out.window,window_type,"",true)){out.reason="economy_window_type_guard";return false;}
    std::int32_t count=0;void**items=nullptr;const char*failure=nullptr;
    if(!core_.list(core_.pointer(out.window,0x58),count,items,failure)||count<0||count>int(ne::kMaxRows)){out.reason=failure?failure:"economy_row_list_guard";return false;}
    s.total=unsigned(count);s.current_window=s.list_valid=true;const auto&f=ne::fixture(route);
    for(std::int32_t i=0;i<count;++i){
        void*row=items[i];if(!core_.typed(row,row_class,"",true)||core_.pointer(row,0x40)!=out.window){s.list_valid=false;out.reason="economy_row_owner_guard";return false;}
        bool exact=kind==1?core_.exact_string(core_.pointer(row,0x78),f.shop_id):
            kind==2?core_.int32(row,0x50)==f.gender_id:
            kind==3?core_.exact_string(core_.pointer(row,0x50),f.type_id):exact_offer(route,row,out.window);
        if(!exact)continue;
        ++s.exact;void*object=core_.game_object(row);bool active=false;
        if(!object||!core_.active(object,active)){s.list_valid=false;out.reason="economy_row_active_guard";return false;}
        if(active){++s.active;++s.compatible;if(s.compatible==1)out.target_row=row;}
    }
    s.complete=true;out.reason=ne::row_reason(s);return !std::strcmp(out.reason,"ready");
}
bool Adapter::probe(ne::Route route,Probe&out,ne::Callback last,unsigned before) noexcept {
    out={};auto&o=out.observation;if(!core_.context(owner_,o.context)){out.reason="economy_context_probe";return false;}
    out.manager=core_.singleton("ManagerInstance","_singleton");
    if(!core_.derived_unity(out.manager,"ManagerInstance","")){out.reason="economy_manager_guard";return false;}
    out.shop=core_.pointer(owner_,0x1a8);void*manager_shop=core_.pointer(out.manager,0x230);
    if(!out.shop){out.reason="economy_owner_shop_missing";return false;}
    if(!core_.typed(out.shop,"ShopManager","",true)){out.reason="economy_owner_shop_type_guard";return false;}
    if(!manager_shop){out.reason="economy_manager_shop_missing";return false;}
    if(!core_.typed(manager_shop,"ShopManager","",true)){out.reason="economy_manager_shop_type_guard";return false;}
    if(manager_shop!=out.shop){out.reason="economy_manager_shop_mismatch";return false;}
    if(!core_.pointer(out.manager,0x198)){out.reason="economy_shop_net_missing";return false;}
    o.shop_open=core_.uint8(out.manager,0x123)!=0;o.shop_closed=!o.shop_open;
    o.input_enabled=core_.uint8(out.shop,0xe0)!=0;
    void*loading_object=core_.game_object(core_.pointer(out.shop,0x50));bool loading=false;
    o.loading_active=loading_object&&core_.active(loading_object,loading)&&loading;
    // EntryBase.OnClick pushes the destination GameObject; +0x88 is stale on ShopRow.
    std::int32_t depth=0;void**stack=nullptr;const char*stack_reason=nullptr;
    if(!core_.list(core_.pointer(out.shop,0xa0),depth,stack,stack_reason)||depth<0||depth>16){out.reason="economy_navigation_stack_guard";return false;}
    bool navigation_active=true;bool menu_sentinel=false;
    if(depth){
        void*top=stack[depth-1];bool active=false;unsigned matches=0;
        if(!core_.typed(top,"GameObject","UnityEngine",true)||!core_.active(top,active)){out.reason="economy_navigation_top_guard";return false;}
        navigation_active=active;
        static const char*types[]={"ShopWindow","GenderWindow","ItemTypeWindow","ItemWindow","WardrobeWindow"};
        for(unsigned i=0;i<5;++i){void*w=core_.pointer(out.shop,0x60+i*8);
            if(core_.typed(w,types[i],"",true)&&core_.game_object(w)==top){out.window=w;out.window_kind=i+1;++matches;}}
        if(matches!=1){
            // Original OpenShop pushes the exact Clothing menu GameObject before
            // OnClickClothing pushes a BaseWindow. It is not a catalog row/window.
            if(matches==0&&depth==1&&top==core_.pointer(out.shop,0xe8))menu_sentinel=true;
            else {out.reason="economy_navigation_owner_guard";return false;}
        }
    }
    o.current_shop=out.window_kind==1;o.current_gender=out.window_kind==2;o.current_type=out.window_kind==3;o.current_item=out.window_kind==4;
    o.window_transition=last!=ne::Callback::None&&before!=out.window_kind;
    const auto&f=ne::fixture(route);
    bool selected_shop=core_.exact_string(core_.pointer(out.shop,0x140),f.shop_id);
    bool selected_gender=core_.int32(out.shop,0x148)==f.gender_id;
    bool selected_type=f.direct_items||core_.exact_string(core_.pointer(out.shop,0x150),f.type_id);
    o.selected_shop=selected_shop;o.selected_gender=selected_gender;o.selected_type=selected_type;
    o.selected_fixture=selected_shop&&selected_gender&&selected_type;
    o.selected_offer=core_.exact_string(core_.pointer(out.shop,0x158),f.offer_id);
    if(out.window_kind>=1&&out.window_kind<=4){const char*rc=out.window_kind==1?"EntryShop":out.window_kind==2?"EntryGender":out.window_kind==3?"EntryItemType":"EntryItem";o.target_row=scan(route,out,rc,out.window_kind);}
    out.wardrobe=core_.pointer(out.shop,0x80);
    bool offer_binding=false;void*bound_offer_row=nullptr;
    if(core_.typed(out.wardrobe,"WardrobeWindow","",true)){
        o.item_loading_active=core_.uint8(out.wardrobe,0x148)!=0;
        void*selected_row=core_.pointer(out.wardrobe,0x138);
        // EntryItem.OnClick binds this row before the response pushes Wardrobe.
        // Its owner remains the same ItemWindow, even when stack top is Wardrobe.
        void*item_window=core_.pointer(out.shop,0x78);
        bool selected_exact=(out.window_kind==4||out.window_kind==5)&&
            core_.typed(item_window,"ItemWindow","",true)&&exact_offer(route,selected_row,item_window);
        if(selected_exact){
            std::int32_t count=0;void**items=nullptr;const char*failure=nullptr;
            selected_exact=core_.list(core_.pointer(item_window,0x58),count,items,failure)&&count>=0&&count<=int(ne::kMaxRows);
            unsigned selected_count=0,offer_count=0;
            for(std::int32_t i=0;selected_exact&&i<count;++i){
                void*row=items[i];
                if(!core_.typed(row,"EntryItem","",true)||core_.pointer(row,0x40)!=item_window){selected_exact=false;break;}
                if(row==selected_row)++selected_count;
                if(exact_offer(route,row,item_window))++offer_count;
            }
            selected_exact=selected_exact&&selected_count==1&&offer_count==1;
        }
        if(selected_exact)bound_offer_row=selected_row;
        offer_binding=o.selected_fixture&&o.selected_offer&&selected_exact;
        bool wardrobe_active=false;
        o.ownership_generation=offer_binding&&!o.item_loading_active&&core_.active(core_.game_object(out.wardrobe),wardrobe_active)&&wardrobe_active;
        bool buy=false,np=false;void*buy_button=core_.pointer(out.wardrobe,0xa0);void*np_button=core_.pointer(out.wardrobe,0xb0);
        o.buy_active=core_.active(core_.game_object(buy_button),buy)&&buy;
        // dump.cs: WardrobeWindow.btnBuyNP+0xb0 is GameObject, not Component.
        o.buy_np_active=core_.typed(np_button,"GameObject","UnityEngine",true)&&core_.active(np_button,np)&&np;
        o.label_buy=core_.exact_string(core_.pointer(core_.pointer(out.wardrobe,0xa8),0xe0),"BUY");
        o.label_purchased=core_.exact_string(core_.pointer(core_.pointer(out.wardrobe,0xa8),0xe0),"PURCHASED");
        void*selected=nullptr;o.gift_selected=core_.selected(core_.pointer(out.shop,0x30),selected)&&selected==core_.pointer(out.wardrobe,0xb8);
    }
    // EntryItem.OnClick clears isLoadingItem synchronously for non-preview
    // offers; the original ownership response activates Wardrobe afterwards.
    // Only our actual OfferRow return or its bounded OfferWait may observe
    // this gap. This cannot create ownership_generation or authorize Buy.
    o.offer_transition_bound=(out.window_kind==4||out.window_kind==5)&&offer_binding&&o.shop_open&&
        !std::strcmp(ne::context_reason(o.context),"ready")&&
        (offer_wait_||(last==ne::Callback::OfferRow&&before==4));
    if(depth&&!navigation_active&&!((out.window_kind==4||out.window_kind==5)&&offer_binding&&(o.item_loading_active||o.ownership_generation||o.offer_transition_bound))){out.reason="economy_navigation_top_inactive";return false;}
    void*price_row=out.target_row;if(!price_row)price_row=bound_offer_row;
    if(price_row){o.offer_non_bundle=!core_.uint8(price_row,0xb0);o.price_canonical=core_.uint_text(core_.pointer(price_row,0x58),o.price_crystals)&&core_.uint_text(core_.pointer(price_row,0x60),o.price_np);}
    o.wallet_fresh=core_.uint_text(core_.pointer(out.shop,0x48),o.wallet_crystals)&&core_.uint_text(core_.pointer(out.shop,0x40),o.wallet_np);
    o.purchase_cycle_complete=economy_callback_generation::ready()&&o.input_enabled&&!o.loading_active&&o.wallet_fresh&&o.ownership_generation;
    bool sa=false,ea=false;o.shop_object_active=core_.active(core_.game_object(out.shop),sa)&&sa;o.event_active=core_.active(core_.game_object(core_.pointer(out.shop,0x30)),ea)&&ea;
    void*selected=nullptr;o.clothing_selected=core_.selected(core_.pointer(out.shop,0x30),selected)&&selected==core_.pointer(out.shop,0xe8);
    if(menu_sentinel&&(!o.shop_open||!navigation_active||!o.shop_object_active||!o.event_active||!o.clothing_selected)){
        out.reason="economy_navigation_menu_shell_guard";return false;
    }
    out.reason="ready";return true;
}
bool Adapter::capture(ne::Route route,ne::Observation&value,const char*&reason) noexcept {
    Probe p{};bool ok=probe(route,p,last_,before_);value=p.observation;reason=ok?nullptr:p.reason;last_=ne::Callback::None;return ok;
}
ne::InvokeResult Adapter::invoke(ne::Route route,ne::Currency currency,ne::Callback cb,const char*&reason) noexcept {
    Probe p{};if(!probe(route,p)){reason=p.reason;return ne::InvokeResult::GuardRejected;}
    void*receiver=nullptr,*method=nullptr,*args[1]{};before_=p.window_kind;last_=cb;
    if(cb==ne::Callback::OpenShop){receiver=p.manager;method=core_.method("ManagerInstance","OpenShop",0,0x439810);}
    else if(cb==ne::Callback::Clothing){receiver=p.shop;method=core_.method("ShopManager","OnClickClothing",0,0x4acce0);}
    else if(cb==ne::Callback::Companions||cb==ne::Callback::Locomotions){
        if(!p.observation.current_shop||!p.observation.input_enabled||p.observation.loading_active){reason="economy_top_catalog_invoke_guard";return ne::InvokeResult::GuardRejected;}
        receiver=p.shop;method=cb==ne::Callback::Companions?core_.method("ShopManager","OnClickCompanions",0,0x4acda0):core_.method("ShopManager","OnClickLocomotions",0,0x4acfe0);
    }
    else if(cb==ne::Callback::Buy){
        if(ne::ownership(p.observation)!=ne::Ownership::Unowned||!p.observation.buy_active||
           (currency==ne::Currency::NP&&!p.observation.buy_np_active)){reason="economy_buy_active_ownership_guard";return ne::InvokeResult::GuardRejected;}
        receiver=p.wardrobe;method=currency==ne::Currency::NP?core_.method("WardrobeWindow","OnClickBuyNP",0,0x4b75e0):core_.method("WardrobeWindow","OnClickBuy",0,0x4b7670);}
    else {if(std::strcmp(ne::row_reason(p.observation.row),"ready")||!p.target_row){reason="economy_invoke_row_guard";return ne::InvokeResult::GuardRejected;}
        receiver=p.target_row;
        // Exact persistent Object arguments recovered from pristine resources.assets.
        std::size_t destination_offset=cb==ne::Callback::ShopRow?0x68:cb==ne::Callback::GenderRow?0x70:cb==ne::Callback::TypeRow?0x78:0x80;
        const char*destination_type=cb==ne::Callback::ShopRow?"GenderWindow":cb==ne::Callback::GenderRow?"ItemTypeWindow":cb==ne::Callback::TypeRow?"ItemWindow":"WardrobeWindow";
        args[0]=core_.pointer(p.shop,destination_offset);
        if(!core_.typed(args[0],destination_type,"",true)||args[0]==p.window){reason="economy_destination_window_guard";return ne::InvokeResult::GuardRejected;}
        const char*type=cb==ne::Callback::ShopRow?"EntryShop":cb==ne::Callback::GenderRow?"EntryGender":cb==ne::Callback::TypeRow?"EntryItemType":"EntryItem";
        std::uintptr_t rva=cb==ne::Callback::ShopRow?0x4aaaf0:cb==ne::Callback::GenderRow?0x4a86e0:cb==ne::Callback::TypeRow?0x4a8de0:0x4a9790;method=core_.method(type,"OnClick",1,rva);}
    if(!receiver||!method){reason="economy_callback_metadata_guard";return ne::InvokeResult::GuardRejected;}
    bool row=cb==ne::Callback::ShopRow||cb==ne::Callback::GenderRow||cb==ne::Callback::TypeRow||cb==ne::Callback::OfferRow;
    if(!core_.invoke(method,receiver,row?args:nullptr)){reason="economy_managed_exception";return ne::InvokeResult::ManagedException;}
    reason="economy_callback_started";return ne::InvokeResult::Started;
}
void snapshot(const ne::Module&m,const Probe&p,SnapshotSink&s) noexcept {
    const auto&o=p.observation;const auto&machine=m.machine();const auto&f=ne::fixture(machine.route);
    s.integer("phase",static_cast<unsigned>(machine.phase));s.string("status",machine.status);
    s.string("route",machine.route==ne::Route::Companion?"companion":machine.route==ne::Route::Locomotion?"locomotion":"wardrobe_female_torso");
    s.string("shop_id",f.shop_id);s.integer("gender_id",f.gender_id);s.string("type_id",f.type_id);s.string("offer_id",f.offer_id);s.string("item_id",f.item_id);
    s.boolean("shop_open",o.shop_open);s.boolean("input_enabled",o.input_enabled);s.boolean("loading_active",o.loading_active);s.integer("current_window",p.window_kind);
    s.boolean("row_complete",o.row.complete);s.integer("row_total",o.row.total);s.integer("row_exact",o.row.exact);s.integer("row_active",o.row.active);s.integer("row_compatible",o.row.compatible);
    s.boolean("selected_fixture",o.selected_fixture);s.boolean("selected_offer",o.selected_offer);s.integer("selected_crystals",o.price_crystals);s.integer("selected_np",o.price_np);
    auto own=ne::ownership(o);s.string("ownership",own==ne::Ownership::Owned?"owned":own==ne::Ownership::Unowned?"unowned":"unknown");
    s.integer("wallet_crystals",o.wallet_crystals);s.integer("wallet_np",o.wallet_np);s.boolean("wallet_fresh",o.wallet_fresh);s.boolean("purchase_cycle_complete",o.purchase_cycle_complete);
}
}
