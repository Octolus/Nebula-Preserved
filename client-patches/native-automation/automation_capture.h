#pragma once

#include "automation_desktop.h"
#include "frame_capture_module.h"

namespace nac {

constexpr std::uint32_t kMaxFrameCaptures = 8;

enum class FrameCaptureDispatch : std::uint32_t {
    started = 0,
    request_limit,
    desktop_guard,
    capture_failure,
};

struct FrameCaptureState {
    std::uint32_t requests{};
    nebula_frame_capture::State capture{};
};

struct FrameCaptureResult {
    FrameCaptureDispatch dispatch{FrameCaptureDispatch::capture_failure};
    nebula_frame_capture::RequestResult capture{};
};

inline FrameCaptureResult dispatch_frame_capture(
    FrameCaptureState &state,
    const DesktopProof &desktop,
    const nebula_frame_capture::Api &api,
    const std::uint16_t *trusted_session_directory,
    std::size_t directory_length,
    std::uint64_t sequence,
    bool output_absent) {
    FrameCaptureResult out{};
    if (state.requests >= kMaxFrameCaptures) {
        out.dispatch = FrameCaptureDispatch::request_limit;
        return out;
    }
    // Every authenticated frame.capture command consumes the bounded request
    // budget, including a rejected attempt. This prevents error-path retries
    // from becoming an unbounded rendering or metadata probe.
    ++state.requests;
    if (!desktop.probe_ok || !desktop.matches_session || desktop.receives_input) {
        out.dispatch = FrameCaptureDispatch::desktop_guard;
        return out;
    }
    out.capture = nebula_frame_capture::request_game_frame(
        api, state.capture, trusted_session_directory, directory_length,
        sequence, output_absent);
    out.dispatch = out.capture.result == nebula_frame_capture::Result::started
        ? FrameCaptureDispatch::started
        : FrameCaptureDispatch::capture_failure;
    return out;
}

} // namespace nac
