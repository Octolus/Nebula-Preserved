#include "economy_callback_generations.h"
#include <atomic>

namespace {
std::atomic<std::uint64_t> shop_info_generation{};
std::atomic<std::uint64_t> purchases_generation{};
std::uint64_t baseline_shop_info{},baseline_purchases{};
bool armed{};
}
namespace economy_callback_generation {
void arm() noexcept {
    baseline_shop_info=shop_info_generation.load(std::memory_order_acquire);
    baseline_purchases=purchases_generation.load(std::memory_order_acquire);
    armed=true;
}
void disarm() noexcept {armed=false;}
bool ready() noexcept {
    return armed&&shop_info_generation.load(std::memory_order_acquire)>baseline_shop_info&&
        purchases_generation.load(std::memory_order_acquire)>baseline_purchases;
}
std::uint64_t shop_info() noexcept{return shop_info_generation.load(std::memory_order_acquire);}
std::uint64_t purchases() noexcept{return purchases_generation.load(std::memory_order_acquire);}
void advance_shop_info() noexcept {shop_info_generation.fetch_add(1,std::memory_order_release);}
void advance_purchases() noexcept {purchases_generation.fetch_add(1,std::memory_order_release);}
}
