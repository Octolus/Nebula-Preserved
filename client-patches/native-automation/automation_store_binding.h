#pragma once

namespace nac_store_binding {

// Primitive-only diagnostics for the shipped Nexus store ownership graph.
// No Unity object address is retained or exposed.
struct Observation {
    bool manager_present{};
    bool manager_derived{};
    bool ps4_shop_present{};
    bool ps4_shop_exact{};
    bool manager_shop_present{};
    bool manager_shop_exact{};
    bool manager_shop_same{};
    bool shop_net_present{};
};

inline const char *reason(const Observation &value) noexcept {
    if (!value.manager_present) return "store_manager_missing";
    if (!value.manager_derived) return "store_manager_type_guard";
    if (!value.ps4_shop_present) return "store_ps4_shop_missing";
    if (!value.ps4_shop_exact) return "store_ps4_shop_type_guard";
    if (!value.manager_shop_present) return "store_manager_shop_missing";
    if (!value.manager_shop_exact) return "store_manager_shop_type_guard";
    if (!value.manager_shop_same) return "store_manager_shop_mismatch";
    if (!value.shop_net_present) return "store_shop_net_missing";
    return "ready";
}

inline bool ready(const Observation &value) noexcept {
    return value.manager_present && value.manager_derived &&
        value.ps4_shop_present && value.ps4_shop_exact &&
        value.manager_shop_present && value.manager_shop_exact &&
        value.manager_shop_same && value.shop_net_present;
}

} // namespace nac_store_binding
