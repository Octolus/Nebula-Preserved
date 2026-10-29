#pragma once

#include <cstddef>
#include <cwchar>

namespace nebula_release_v3 {

constexpr std::size_t kSessionPathMax = 1024;

inline bool copy_path(const wchar_t* source, wchar_t (&target)[kSessionPathMax]) noexcept {
    if (!source) return false;
    const std::size_t length = std::wcslen(source);
    if (!length || length >= kSessionPathMax) return false;
    std::wmemcpy(target, source, length + 1);
    return true;
}

inline bool remove_leaf(wchar_t (&path)[kSessionPathMax], const wchar_t* expected = nullptr) noexcept {
    wchar_t* slash = std::wcsrchr(path, L'\\');
    if (!slash || slash <= path + 2 || !slash[1]) return false;
    if (expected && std::wcscmp(slash + 1, expected)) return false;
    *slash = 0;
    return true;
}

inline bool normal_suffix(const wchar_t* value) noexcept {
    if (!value || !*value) return false;
    for (; *value; ++value) {
        if (!((*value >= L'a' && *value <= L'z') ||
              (*value >= L'A' && *value <= L'Z') ||
              (*value >= L'0' && *value <= L'9') || *value == L'-')) return false;
    }
    return true;
}

inline bool cohort_name(const wchar_t* begin, const wchar_t* end) noexcept {
    const std::ptrdiff_t length = end - begin;
    if (length < 1 || length > 40) return false;
    for (const wchar_t* p = begin; p != end; ++p) {
        if (!((*p >= L'a' && *p <= L'z') || (*p >= L'0' && *p <= L'9') || *p == L'-'))
            return false;
    }
    return true;
}

inline bool starts_with(const wchar_t* value, const wchar_t* prefix) noexcept {
    return value && prefix && !std::wcsncmp(value, prefix, std::wcslen(prefix));
}

inline bool session_path_allowed(const wchar_t* module_path, const wchar_t* directory,
                                 const wchar_t* test_slot) noexcept {
    wchar_t root[kSessionPathMax]{};
    if (!copy_path(module_path, root) || !directory) return false;

    // Preserve the original single-client rule: three parents above the module
    // and one direct native-auto-session-* child using the existing suffix grammar.
    wchar_t normal_root[kSessionPathMax]{};
    std::wmemcpy(normal_root, root, kSessionPathMax);
    if (remove_leaf(normal_root, L"GameAssembly.dll") && remove_leaf(normal_root) &&
        remove_leaf(normal_root)) {
        wchar_t prefix[kSessionPathMax]{};
        if (std::swprintf(prefix, kSessionPathMax, L"%ls\\native-auto-session-", normal_root) > 0 &&
            starts_with(directory, prefix) && normal_suffix(directory + std::wcslen(prefix))) return true;
    }

    // Fixed private cohort: the module and IPC directory must independently
    // identify the same exact slot under the same direct work root.
    if (!test_slot || (std::wcscmp(test_slot, L"1") && std::wcscmp(test_slot, L"2"))) return false;
    const wchar_t* slot_leaf = test_slot[0] == L'1' ? L"slot-1" : L"slot-2";
    wchar_t cohort_root[kSessionPathMax]{};
    std::wmemcpy(cohort_root, root, kSessionPathMax);
    if (!remove_leaf(cohort_root, L"GameAssembly.dll") || !remove_leaf(cohort_root, slot_leaf) ||
        !remove_leaf(cohort_root, L"two-client-package")) return false;
    wchar_t prefix[kSessionPathMax]{};
    if (std::swprintf(prefix, kSessionPathMax, L"%ls\\native-auto-cohort-", cohort_root) <= 0 ||
        !starts_with(directory, prefix)) return false;
    const wchar_t* name = directory + std::wcslen(prefix);
    const wchar_t* slash = std::wcschr(name, L'\\');
    return slash && cohort_name(name, slash) && !std::wcscmp(slash + 1, slot_leaf);
}

} // namespace nebula_release_v3
