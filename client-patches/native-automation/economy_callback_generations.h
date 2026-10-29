#pragma once
#include <cstdint>

namespace economy_callback_generation {
void arm() noexcept;
void disarm() noexcept;
bool ready() noexcept;
std::uint64_t shop_info() noexcept;
std::uint64_t purchases() noexcept;
void advance_shop_info() noexcept;
void advance_purchases() noexcept;
}

// Exact GameAssembly wrappers pass the original string[] response after the
// original callback returned. Validation is synchronous; no pointer is kept.
extern "C" __declspec(dllexport) void NebulaAutomation_EconomyShopInfoCompleted(void *response) noexcept;
extern "C" __declspec(dllexport) void NebulaAutomation_EconomyPurchasesCompleted(void *response) noexcept;
