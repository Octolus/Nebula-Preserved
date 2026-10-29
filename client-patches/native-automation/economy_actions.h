#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace nebula_economy_wire {
enum Action : std::uint8_t { None,Open,SelectWardrobe,SelectCompanion,SelectLocomotion,BuyCrystals,BuyNP };
inline const char *name(Action a) {
    switch(a){
    case Open:return "shop.open";
    case SelectWardrobe:return "shop.select_wardrobe_fixture";
    case SelectCompanion:return "shop.select_companion_fixture";
    case SelectLocomotion:return "shop.select_locomotion_fixture";
    case BuyCrystals:return "shop.buy_selected_crystals";
    case BuyNP:return "shop.buy_selected_np";
    default:return "invalid";
    }
}
inline Action parse(const char *p,std::size_t n) {
    for(Action a:{Open,SelectWardrobe,SelectCompanion,SelectLocomotion,BuyCrystals,BuyNP}){
        const char*s=name(a);if(std::strlen(s)==n&&!std::memcmp(p,s,n))return a;
    }
    return None;
}
inline bool no_argument(Action a){return a!=None;}
}
