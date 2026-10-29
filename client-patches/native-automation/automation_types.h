#pragma once

#include <cstdint>

namespace nac {

using ClassParent = void *(*)(void *);
using ClassMatches = bool (*)(void *, const char *, const char *);

// IL2CPP boxes enum-return values as the enum's managed class, not as
// System.Int32.  Callers must derive the exact expected class from the
// invoked MethodInfo return type and reject every other boxed class even
// though all enum backing values are int32_t.
inline bool exact_return_box_class(const void *box_class,
                                   const void *return_class) {
    return box_class && return_class && box_class == return_class;
}

// Bounded inheritance walk shared by the production runtime guard and its
// authored fake hierarchy test. It never accepts a name-only object without
// following the actual IL2CPP class-parent chain.
inline bool class_is_or_derives(void *klass,
                                const char *expected_name,
                                const char *expected_namespace,
                                ClassParent parent,
                                ClassMatches matches) {
    if (!klass || !expected_name || !expected_namespace || !parent || !matches)
        return false;
    for (std::uint32_t depth = 0; klass && depth < 32; ++depth, klass = parent(klass))
        if (matches(klass, expected_name, expected_namespace)) return true;
    return false;
}

} // namespace nac
