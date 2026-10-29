#pragma once

#include <cstddef>
#include <cstdint>
#include "frame_capture_policy.h"

namespace nebula_frame_capture {

constexpr std::uintptr_t kCaptureScreenshotRva = 0x1be46a0;
constexpr const char *kImageName = "UnityEngine.ScreenCaptureModule.dll";
constexpr const char *kNamespace = "UnityEngine";
constexpr const char *kClassName = "ScreenCapture";
constexpr const char *kMethodName = "CaptureScreenshot";

using Readable = bool (*)(const void *, std::size_t);
using DomainGet = void *(*)();
using DomainGetAssemblies = void **(*)(void *, std::size_t *);
using AssemblyGetImage = void *(*)(void *);
using ImageGetName = const char *(*)(void *);
using ClassFromName = void *(*)(void *, const char *, const char *);
using ClassGetMethodFromName = void *(*)(void *, const char *, int);
using StringNewUtf16 = void *(*)(const std::uint16_t *, std::int32_t);
using RuntimeInvoke = void *(*)(const void *, void *, void **, void **);

struct Api {
    std::uintptr_t game_base{};
    Readable readable{};
    DomainGet domain_get{};
    DomainGetAssemblies domain_get_assemblies{};
    AssemblyGetImage assembly_get_image{};
    ImageGetName image_get_name{};
    ClassFromName class_from_name{};
    ClassGetMethodFromName class_get_method_from_name{};
    StringNewUtf16 string_new_utf16{};
    RuntimeInvoke runtime_invoke{};
};

enum class Result : std::uint32_t {
    started = 0,
    invalid_directory,
    invalid_sequence,
    sequence_not_increasing,
    output_exists,
    path_too_long,
    api_unavailable,
    image_unavailable,
    image_ambiguous,
    class_unavailable,
    method_unavailable,
    method_pointer_mismatch,
    string_allocation_failed,
    managed_exception,
};

struct State {
    std::uint64_t last_started_sequence{};
};

struct RequestResult {
    Result result{Result::api_unavailable};
    FramePath path{};
};

const void *resolve_capture_method(const Api &api, Result &failure);
RequestResult request_game_frame(const Api &api,
                                 State &state,
                                 const std::uint16_t *trusted_session_directory,
                                 std::size_t directory_length,
                                 std::uint64_t sequence,
                                 bool output_absent);
const char *result_name(Result result);

} // namespace nebula_frame_capture
