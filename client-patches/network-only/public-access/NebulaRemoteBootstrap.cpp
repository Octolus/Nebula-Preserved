#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>

#include <array>
#include <cstdint>
#include <cstring>
#include <cwchar>
#include <string>
#include <vector>

#include "NebulaRemoteBootstrap.h"
#include "RemoteTransportPin.h"

namespace {
constexpr std::size_t kMaximumConfig = 4096;
constexpr wchar_t kLoopbackOrigin[] = L"http://127.0.0.1:38080";
constexpr wchar_t kSidecarName[] = L"NebulaRemoteTransport.exe";
constexpr char kGameExeSha256[] =
    "77bdecc37804194305c2402be5ac0851570f395bf9af3fb4ee03030c6d779d0d";

struct RemoteState {
    INIT_ONCE start_once = INIT_ONCE_STATIC_INIT;
    bool configured{};
    bool ready{};
    HANDLE job{};
};
RemoteState g_remote;

bool read_file(const wchar_t *path, std::vector<std::uint8_t> &out,
               std::size_t maximum, HANDLE *held = nullptr) {
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr,
                              OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
                              nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    BY_HANDLE_FILE_INFORMATION info{};
    bool okay = GetFileInformationByHandle(file, &info) &&
        !(info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) &&
        info.nFileSizeHigh == 0 && info.nFileSizeLow > 0 && info.nFileSizeLow <= maximum;
    if (okay) {
        out.resize(info.nFileSizeLow);
        DWORD got = 0;
        okay = ReadFile(file, out.data(), info.nFileSizeLow, &got, nullptr) &&
            got == info.nFileSizeLow;
    }
    if (okay && held) {
        LARGE_INTEGER zero{};
        okay = SetFilePointerEx(file, zero, nullptr, FILE_BEGIN) != FALSE;
        if (okay) *held = file;
    }
    if (!okay || !held) CloseHandle(file);
    return okay;
}

bool sha256(const std::vector<std::uint8_t> &bytes,
            std::array<std::uint8_t, 32> &digest) {
    BCRYPT_ALG_HANDLE algorithm{};
    BCRYPT_HASH_HANDLE hash{};
    DWORD object_size = 0, result_size = 0;
    std::vector<std::uint8_t> object;
    bool okay = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM,
                                             nullptr, 0) >= 0 &&
        BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                          reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size),
                          &result_size, 0) >= 0;
    if (okay) {
        object.resize(object_size);
        okay = BCryptCreateHash(algorithm, &hash, object.data(), object_size,
                                nullptr, 0, 0) >= 0 &&
            BCryptHashData(hash, const_cast<PUCHAR>(bytes.data()),
                           static_cast<ULONG>(bytes.size()), 0) >= 0 &&
            BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) >= 0;
    }
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    return okay;
}

bool decode_hex(const char *text, std::array<std::uint8_t, 32> &out) {
    if (!text || std::strlen(text) != out.size() * 2) return false;
    auto nibble = [](char value) -> int {
        if (value >= '0' && value <= '9') return value - '0';
        if (value >= 'a' && value <= 'f') return value - 'a' + 10;
        return -1;
    };
    for (std::size_t i = 0; i < out.size(); ++i) {
        int high = nibble(text[i * 2]), low = nibble(text[i * 2 + 1]);
        if (high < 0 || low < 0) return false;
        out[i] = static_cast<std::uint8_t>((high << 4) | low);
    }
    return true;
}

bool hash_matches(const std::vector<std::uint8_t> &bytes, const char *expected) {
    std::array<std::uint8_t, 32> actual{}, wanted{};
    return decode_hex(expected, wanted) && sha256(bytes, actual) && actual == wanted;
}

bool utf8_to_wide(const std::string &value, std::wstring &out) {
    if (value.empty()) return false;
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
                                    static_cast<int>(value.size()), nullptr, 0);
    if (count <= 0) return false;
    out.resize(static_cast<std::size_t>(count));
    return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
                               static_cast<int>(value.size()), out.data(), count) == count;
}

bool direct_child(const std::wstring &path, const std::wstring &directory) {
    if (path.size() <= directory.size() + 1 ||
        _wcsnicmp(path.c_str(), directory.c_str(), directory.size()) != 0 ||
        path[directory.size()] != L'\\') return false;
    return path.find_first_of(L"\\/", directory.size() + 1) == std::wstring::npos;
}

bool exact_url(const std::wstring &url, const wchar_t *origin) {
    std::size_t size = std::wcslen(origin);
    if (url.size() < size || url.compare(0, size, origin)) return false;
    if (url.size() == size) return true;
    wchar_t boundary = url[size];
    return boundary == L'/' || boundary == L'?' || boundary == L'#';
}

bool valid_port(const std::string &value) {
    if (value.empty() || value.size() > 5 || (value.size() > 1 && value[0] == '0')) return false;
    unsigned port = 0;
    for (char byte : value) {
        if (byte < '0' || byte > '9') return false;
        port = port * 10u + static_cast<unsigned>(byte - '0');
    }
    return port >= 1u && port <= 65535u;
}

bool module_directory(std::wstring &directory) {
    HMODULE self{};
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                            GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            reinterpret_cast<LPCWSTR>(&NebulaRemote_EnsureReady), &self)) return false;
    std::vector<wchar_t> path(32768);
    DWORD length = GetModuleFileNameW(self, path.data(), static_cast<DWORD>(path.size()));
    if (!length || length >= path.size()) return false;
    std::wstring full(path.data(), length);
    std::size_t slash = full.find_last_of(L"\\/");
    if (slash == std::wstring::npos) return false;
    directory = full.substr(0, slash);
    return true;
}

bool current_game_is_pinned() {
    std::vector<wchar_t> path(32768);
    DWORD length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    if (!length || length >= path.size()) return false;
    std::size_t slash = std::wstring(path.data(), length).find_last_of(L"\\/");
    std::wstring leaf = slash == std::wstring::npos
        ? std::wstring(path.data(), length)
        : std::wstring(path.data() + slash + 1, length - slash - 1);
    if (_wcsicmp(leaf.c_str(), L"Nebula Realms.exe")) return false;
    std::vector<std::uint8_t> bytes;
    return read_file(path.data(), bytes, 64u * 1024u * 1024u) &&
        hash_matches(bytes, kGameExeSha256);
}

bool parse_profile(const std::wstring &public_origin) {
    wchar_t local[MAX_PATH]{};
    DWORD local_count = GetEnvironmentVariableW(L"LOCALAPPDATA", local, MAX_PATH);
    if (!local_count || local_count >= MAX_PATH) return false;
    std::wstring directory = std::wstring(local) + L"\\NebulaPreservation";
    std::wstring config_path = directory + L"\\remote-game.conf";
    std::vector<std::uint8_t> bytes;
    if (!read_file(config_path.c_str(), bytes, kMaximumConfig)) return false;
    std::string text(bytes.begin(), bytes.end());
    if (text.find('\r') != std::string::npos || text.find('\0') != std::string::npos) return false;

    std::array<std::string, 7> keys{{"format", "server_url", "gateway_port", "api_port",
                                     "first_scene_port", "last_scene_port", "ca_file"}};
    std::array<std::string, 7> values{};
    std::array<bool, 7> seen{};
    std::string ca_hash;
    bool saw_ca_hash = false;
    std::size_t offset = 0;
    while (offset <= text.size()) {
        std::size_t end = text.find('\n', offset);
        if (end == std::string::npos) end = text.size();
        std::string line = text.substr(offset, end - offset);
        bool matched = false;
        for (std::size_t i = 0; i < keys.size(); ++i) {
            std::string prefix = keys[i] + "=";
            if (line.rfind(prefix, 0) == 0) {
                if (seen[i]) return false;
                seen[i] = true;
                values[i] = line.substr(prefix.size());
                matched = true;
                break;
            }
        }
        if (!matched && line.rfind("ca_sha256=", 0) == 0) {
            if (saw_ca_hash) return false;
            saw_ca_hash = true;
            ca_hash = line.substr(10);
            matched = true;
        }
        if (!matched && !line.empty()) return false;
        if (end == text.size()) break;
        offset = end + 1;
    }
    for (bool value : seen) if (!value) return false;
    if (!saw_ca_hash || values[0] != "nebula-remote-transport-v1" ||
        !valid_port(values[2]) || values[3] != "38080" || values[4] != "28000" ||
        values[5] != "28031") return false;
    std::wstring configured_origin, ca_path;
    if (!utf8_to_wide(values[1], configured_origin) || configured_origin != public_origin ||
        !utf8_to_wide(values[6], ca_path)) return false;
    wchar_t full[32768]{};
    DWORD full_count = GetFullPathNameW(ca_path.c_str(), static_cast<DWORD>(std::size(full)),
                                       full, nullptr);
    if (!full_count || full_count >= std::size(full) || ca_path != full ||
        !direct_child(ca_path, directory)) return false;
    std::vector<std::uint8_t> ca;
    return read_file(ca_path.c_str(), ca, 1024u * 1024u) && hash_matches(ca, ca_hash.c_str());
}

std::wstring ready_event_name() {
    FILETIME creation{}, exit{}, kernel{}, user{};
    if (!GetProcessTimes(GetCurrentProcess(), &creation, &exit, &kernel, &user)) return {};
    ULARGE_INTEGER stamp{};
    stamp.LowPart = creation.dwLowDateTime;
    stamp.HighPart = creation.dwHighDateTime;
    wchar_t name[160]{};
    int count = swprintf_s(name, L"Local\\NebulaRemoteTransport-%lu-%llu",
                           GetCurrentProcessId(), static_cast<unsigned long long>(stamp.QuadPart));
    return count > 0 ? std::wstring(name, static_cast<std::size_t>(count)) : std::wstring();
}

BOOL CALLBACK start_remote(PINIT_ONCE, PVOID, PVOID *) {
    if (!g_remote.configured || !current_game_is_pinned()) return TRUE;
    std::wstring directory;
    if (!module_directory(directory)) return TRUE;
    std::wstring executable = directory + L"\\" + kSidecarName;
    std::vector<std::uint8_t> bytes;
    HANDLE pinned_file{};
    if (!read_file(executable.c_str(), bytes, 64u * 1024u * 1024u, &pinned_file) ||
        !hash_matches(bytes, NEBULA_REMOTE_TRANSPORT_SHA256)) {
        if (pinned_file) CloseHandle(pinned_file);
        return TRUE;
    }
    std::wstring event_name = ready_event_name();
    if (event_name.empty()) { CloseHandle(pinned_file); return TRUE; }
    HANDLE ready = CreateEventW(nullptr, TRUE, FALSE, event_name.c_str());
    if (!ready || GetLastError() == ERROR_ALREADY_EXISTS) {
        if (ready) CloseHandle(ready);
        CloseHandle(pinned_file);
        return TRUE;
    }
    HANDLE job = CreateJobObjectW(nullptr, nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!job || !SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                          &limits, sizeof(limits))) {
        if (job) CloseHandle(job);
        CloseHandle(ready);
        CloseHandle(pinned_file);
        return TRUE;
    }
    std::wstring command = L"\"" + executable + L"\"";
    std::vector<wchar_t> mutable_command(command.begin(), command.end());
    mutable_command.push_back(L'\0');
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    bool okay = CreateProcessW(executable.c_str(), mutable_command.data(), nullptr, nullptr,
                               FALSE, CREATE_SUSPENDED | CREATE_NO_WINDOW, nullptr,
                               directory.c_str(), &startup, &process) != FALSE;
    if (okay) okay = AssignProcessToJobObject(job, process.hProcess) != FALSE;
    if (okay) okay = ResumeThread(process.hThread) != static_cast<DWORD>(-1);
    CloseHandle(pinned_file);
    if (okay) {
        HANDLE waits[]{ready, process.hProcess};
        okay = WaitForMultipleObjects(2, waits, FALSE, 5000) == WAIT_OBJECT_0;
    }
    if (!okay) TerminateJobObject(job, 0x4e525446u);
    if (process.hThread) CloseHandle(process.hThread);
    if (process.hProcess) CloseHandle(process.hProcess);
    CloseHandle(ready);
    if (!okay) { CloseHandle(job); return TRUE; }
    g_remote.job = job;
    g_remote.ready = true;
    return TRUE;
}
}

bool NebulaRemote_LoadProfile(const std::wstring &public_server_origin) {
    g_remote.configured = parse_profile(public_server_origin);
    return g_remote.configured;
}

bool NebulaRemote_IsLoopbackRequest(const std::wstring &url) {
    return exact_url(url, kLoopbackOrigin);
}

bool NebulaRemote_EnsureReady() {
    InitOnceExecuteOnce(&g_remote.start_once, start_remote, nullptr, nullptr);
    return g_remote.ready;
}
