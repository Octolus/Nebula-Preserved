#pragma once

#include <cstddef>
#include <cstdint>

namespace nebula_frame_capture {

constexpr std::size_t kPathCapacity = 1024;
constexpr std::size_t kMaxSessionDirectoryChars = 960;

enum class PathStatus : std::uint32_t {
    ok = 0,
    invalid_directory,
    invalid_sequence,
    sequence_not_increasing,
    output_exists,
    path_too_long,
};

struct FramePath {
    std::uint16_t value[kPathCapacity]{};
    std::size_t length{};
};

inline bool ascii_letter(std::uint16_t value) {
    return (value >= 'A' && value <= 'Z') || (value >= 'a' && value <= 'z');
}

inline bool forbidden_windows_name_character(std::uint16_t value) {
    return value < 32 || value == '<' || value == '>' || value == ':' || value == '"' ||
           value == '|' || value == '?' || value == '*' || value == '/';
}

inline bool valid_session_directory(const std::uint16_t *directory, std::size_t length) {
    if (!directory || length < 3 || length > kMaxSessionDirectoryChars ||
        !ascii_letter(directory[0]) || directory[1] != ':' || directory[2] != '\\' ||
        directory[length - 1] == '\\') return false;

    std::size_t component_start = 3;
    for (std::size_t i = 0; i < length; ++i) {
        const std::uint16_t value = directory[i];
        if (!value) return false;
        if (i != 1 && forbidden_windows_name_character(value)) return false;
        if (value == '\\') {
            if (i == component_start || (i - component_start == 1 && directory[component_start] == '.') ||
                (i - component_start == 2 && directory[component_start] == '.' &&
                 directory[component_start + 1] == '.')) return false;
            component_start = i + 1;
        }
    }
    const std::size_t tail = length - component_start;
    return tail && !(tail == 1 && directory[component_start] == '.') &&
           !(tail == 2 && directory[component_start] == '.' && directory[component_start + 1] == '.');
}

inline PathStatus build_frame_path(const std::uint16_t *trusted_session_directory,
                                   std::size_t directory_length,
                                   std::uint64_t sequence,
                                   std::uint64_t last_started_sequence,
                                   bool output_absent,
                                   FramePath &out) {
    out = FramePath{};
    if (!valid_session_directory(trusted_session_directory, directory_length))
        return PathStatus::invalid_directory;
    if (!sequence) return PathStatus::invalid_sequence;
    if (sequence <= last_started_sequence) return PathStatus::sequence_not_increasing;
    if (!output_absent) return PathStatus::output_exists;

    std::uint16_t digits[20]{};
    std::size_t digit_count = 0;
    for (std::uint64_t value = sequence; value; value /= 10)
        digits[digit_count++] = static_cast<std::uint16_t>('0' + value % 10);
    constexpr std::uint16_t prefix[] = {'\\','f','r','a','m','e','-'};
    constexpr std::uint16_t suffix[] = {'.','p','n','g'};
    const std::size_t required = directory_length + sizeof(prefix) / sizeof(prefix[0]) +
                                 digit_count + sizeof(suffix) / sizeof(suffix[0]);
    if (required + 1 > kPathCapacity) return PathStatus::path_too_long;

    for (std::size_t i = 0; i < directory_length; ++i) out.value[out.length++] = trusted_session_directory[i];
    for (std::uint16_t value : prefix) out.value[out.length++] = value;
    while (digit_count) out.value[out.length++] = digits[--digit_count];
    for (std::uint16_t value : suffix) out.value[out.length++] = value;
    out.value[out.length] = 0;
    return PathStatus::ok;
}

} // namespace nebula_frame_capture
