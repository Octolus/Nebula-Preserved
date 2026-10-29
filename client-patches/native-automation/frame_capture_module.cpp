#include "frame_capture_module.h"

#include <cstring>
#include <limits>

namespace nebula_frame_capture {
namespace {

bool exact_name(const Api &api, const char *actual, const char *expected) {
    const std::size_t length = std::strlen(expected);
    return actual && api.readable(actual, length + 1) && !std::memcmp(actual, expected, length + 1);
}

bool api_ready(const Api &api) {
    return api.game_base && api.readable && api.domain_get && api.domain_get_assemblies &&
           api.assembly_get_image && api.image_get_name && api.class_from_name &&
           api.class_get_method_from_name && api.string_new_utf16 && api.runtime_invoke;
}

Result path_result(PathStatus status) {
    switch (status) {
    case PathStatus::ok: return Result::started;
    case PathStatus::invalid_directory: return Result::invalid_directory;
    case PathStatus::invalid_sequence: return Result::invalid_sequence;
    case PathStatus::sequence_not_increasing: return Result::sequence_not_increasing;
    case PathStatus::output_exists: return Result::output_exists;
    case PathStatus::path_too_long: return Result::path_too_long;
    }
    return Result::api_unavailable;
}

} // namespace

const void *resolve_capture_method(const Api &api, Result &failure) {
    failure = Result::api_unavailable;
    if (!api_ready(api) || api.game_base > std::numeric_limits<std::uintptr_t>::max() - kCaptureScreenshotRva)
        return nullptr;

    void *domain = api.domain_get();
    std::size_t count = 0;
    void **assemblies = domain ? api.domain_get_assemblies(domain, &count) : nullptr;
    if (!assemblies || !count || count > 256 || !api.readable(assemblies, count * sizeof(void *))) {
        failure = Result::image_unavailable;
        return nullptr;
    }

    void *capture_image = nullptr;
    for (std::size_t i = 0; i < count; ++i) {
        void *image = assemblies[i] ? api.assembly_get_image(assemblies[i]) : nullptr;
        const char *name = image ? api.image_get_name(image) : nullptr;
        if (!exact_name(api, name, kImageName)) continue;
        if (capture_image) {
            failure = Result::image_ambiguous;
            return nullptr;
        }
        capture_image = image;
    }
    if (!capture_image) {
        failure = Result::image_unavailable;
        return nullptr;
    }

    void *capture_class = api.class_from_name(capture_image, kNamespace, kClassName);
    if (!capture_class) {
        failure = Result::class_unavailable;
        return nullptr;
    }
    void *method = api.class_get_method_from_name(capture_class, kMethodName, 1);
    if (!method || !api.readable(method, sizeof(std::uintptr_t))) {
        failure = Result::method_unavailable;
        return nullptr;
    }
    std::uintptr_t method_pointer = 0;
    std::memcpy(&method_pointer, method, sizeof(method_pointer));
    if (method_pointer != api.game_base + kCaptureScreenshotRva) {
        failure = Result::method_pointer_mismatch;
        return nullptr;
    }
    failure = Result::started;
    return method;
}

RequestResult request_game_frame(const Api &api,
                                 State &state,
                                 const std::uint16_t *trusted_session_directory,
                                 std::size_t directory_length,
                                 std::uint64_t sequence,
                                 bool output_absent) {
    RequestResult result{};
    const PathStatus path_status = build_frame_path(trusted_session_directory, directory_length, sequence,
                                                    state.last_started_sequence, output_absent, result.path);
    if (path_status != PathStatus::ok) {
        result.result = path_result(path_status);
        return result;
    }

    Result resolve_failure{};
    const void *method = resolve_capture_method(api, resolve_failure);
    if (!method) {
        result.result = resolve_failure;
        return result;
    }
    if (result.path.length > static_cast<std::size_t>(std::numeric_limits<std::int32_t>::max())) {
        result.result = Result::path_too_long;
        return result;
    }
    void *managed_path = api.string_new_utf16(result.path.value, static_cast<std::int32_t>(result.path.length));
    if (!managed_path) {
        result.result = Result::string_allocation_failed;
        return result;
    }

    // Consume before the managed boundary: a callback that throws may already have queued work.
    state.last_started_sequence = sequence;
    // runtime_invoke passes reference-type arguments as the managed object itself.
    // Only value types use an address to their unboxed storage.
    void *arguments[] = {managed_path};
    void *exception = nullptr;
    api.runtime_invoke(method, nullptr, arguments, &exception);
    result.result = exception ? Result::managed_exception : Result::started;
    return result;
}

const char *result_name(Result result) {
    switch (result) {
    case Result::started: return "started";
    case Result::invalid_directory: return "invalid_directory";
    case Result::invalid_sequence: return "invalid_sequence";
    case Result::sequence_not_increasing: return "sequence_not_increasing";
    case Result::output_exists: return "output_exists";
    case Result::path_too_long: return "path_too_long";
    case Result::api_unavailable: return "api_unavailable";
    case Result::image_unavailable: return "image_unavailable";
    case Result::image_ambiguous: return "image_ambiguous";
    case Result::class_unavailable: return "class_unavailable";
    case Result::method_unavailable: return "method_unavailable";
    case Result::method_pointer_mismatch: return "method_pointer_mismatch";
    case Result::string_allocation_failed: return "string_allocation_failed";
    case Result::managed_exception: return "managed_exception";
    }
    return "unknown";
}

} // namespace nebula_frame_capture
