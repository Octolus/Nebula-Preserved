#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wincrypt.h>
#include <cstdint>
#include <cstring>
#include <cwchar>
#include <string>
#include <vector>
#include "NebulaPublicAccess.h"
#include "NebulaRemoteBootstrap.h"

namespace {
constexpr std::uint32_t kAbi = 1;
constexpr std::uintptr_t kReviewedGetRva = 0x1d9b350;
constexpr std::size_t kMaxConfig = 4096;
constexpr std::size_t kMaxOrigin = 512;
constexpr std::size_t kMaxHeader = 512;

struct ManagedString {
    void *klass;
    void *monitor;
    std::int32_t length;
    wchar_t chars[1];
};

using DomainGet = void *(*)();
using DomainAssemblies = void **(*)(void *, std::size_t *);
using AssemblyImage = void *(*)(void *);
using ImageName = const char *(*)(void *);
using ClassFromName = void *(*)(void *, const char *, const char *);
using ClassMethod = const void *(*)(void *, const char *, int);
using RuntimeInvoke = void *(*)(const void *, void *, void **, void **);
using StringNewUtf16 = void *(*)(const std::uint16_t *, std::int32_t);
using GetRequest = void *(*)(void *, const void *);

struct State {
    INIT_ONCE once = INIT_ONCE_STATIC_INIT;
    HMODULE game{};
    GetRequest original_get{};
    RuntimeInvoke invoke{};
    StringNewUtf16 string_new{};
    const void *set_header{};
    const void *set_redirect_limit{};
    std::wstring origin;
    char authorization[kMaxHeader]{};
    bool ready{};
};
State g;

template<class T> T exported(HMODULE module, const char *name) {
    FARPROC raw = GetProcAddress(module, name);
    T result{};
    static_assert(sizeof(result) == sizeof(raw));
    std::memcpy(&result, &raw, sizeof(result));
    return result;
}

bool managed_text(void *value, std::wstring &out) {
    if (!value) return false;
    auto *text = static_cast<ManagedString *>(value);
    if (text->length < 0 || text->length > 32768) return false;
    out.assign(text->chars, text->chars + text->length);
    return true;
}

bool exact_origin(const std::wstring &url) {
    if (url.size() < g.origin.size() || url.compare(0, g.origin.size(), g.origin)) return false;
    if (url.size() == g.origin.size()) return true;
    wchar_t boundary = url[g.origin.size()];
    return boundary == L'/' || boundary == L'?' || boundary == L'#';
}

bool valid_origin(const std::wstring &value) {
    if (value.size() < 10 || value.size() > kMaxOrigin ||
        value.compare(0, 8, L"https://") != 0 || value.back() == L'/') return false;
    std::wstring authority = value.substr(8);
    if (authority.empty() || authority.find_first_of(L"/@?#\\") != std::wstring::npos) return false;
    for (wchar_t c : authority) {
        if (!((c >= L'a' && c <= L'z') || (c >= L'A' && c <= L'Z') ||
              (c >= L'0' && c <= L'9') || c == L'.' || c == L'-' || c == L':' ||
              c == L'[' || c == L']')) return false;
    }
    return true;
}

bool read_file(const wchar_t *path, std::vector<std::uint8_t> &out, std::size_t maximum) {
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    BY_HANDLE_FILE_INFORMATION info{};
    bool okay = GetFileInformationByHandle(file, &info) &&
        !(info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) &&
        info.nFileSizeHigh == 0 && info.nFileSizeLow > 0 && info.nFileSizeLow <= maximum;
    if (okay) {
        out.resize(info.nFileSizeLow);
        DWORD got = 0;
        okay = ReadFile(file, out.data(), info.nFileSizeLow, &got, nullptr) && got == info.nFileSizeLow;
    }
    CloseHandle(file);
    return okay;
}

bool utf8_to_wide(const std::string &value, std::wstring &out) {
    if (value.empty()) return false;
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
                                    static_cast<int>(value.size()), nullptr, 0);
    if (count <= 0) return false;
    out.resize(count);
    return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
                               static_cast<int>(value.size()), out.data(), count) == count;
}

bool load_config(std::wstring &token_path) {
    wchar_t local[MAX_PATH]{};
    DWORD count = GetEnvironmentVariableW(L"LOCALAPPDATA", local, MAX_PATH);
    if (!count || count >= MAX_PATH) return false;
    std::wstring path = std::wstring(local) + L"\\NebulaPreservation\\public-access.conf";
    std::vector<std::uint8_t> bytes;
    if (!read_file(path.c_str(), bytes, kMaxConfig)) return false;
    std::string text(bytes.begin(), bytes.end());
    if (text.find('\r') != std::string::npos || text.find('\0') != std::string::npos) return false;
    std::string format, origin, token;
    bool saw_format = false, saw_origin = false, saw_token = false;
    std::size_t offset = 0;
    while (offset <= text.size()) {
        std::size_t end = text.find('\n', offset);
        if (end == std::string::npos) end = text.size();
        std::string line = text.substr(offset, end - offset);
        if (line.rfind("format=", 0) == 0) {
            if (saw_format) return false;
            saw_format = true; format = line.substr(7);
        } else if (line.rfind("server_url=", 0) == 0) {
            if (saw_origin) return false;
            saw_origin = true; origin = line.substr(11);
        } else if (line.rfind("token_file=", 0) == 0) {
            if (saw_token) return false;
            saw_token = true; token = line.substr(11);
        }
        else if (!line.empty()) return false;
        if (end == text.size()) break;
        offset = end + 1;
    }
    if (!saw_format || !saw_origin || !saw_token ||
        format != "nebula-public-access-v1" || !utf8_to_wide(origin, g.origin) ||
        !valid_origin(g.origin) || !utf8_to_wide(token, token_path)) return false;
    wchar_t full[MAX_PATH]{};
    DWORD n = GetFullPathNameW(token_path.c_str(), MAX_PATH, full, nullptr);
    if (!n || n >= MAX_PATH || token_path != full) return false;
    std::wstring expected = std::wstring(local) + L"\\NebulaPreservation\\";
    if (_wcsnicmp(token_path.c_str(), expected.c_str(), expected.size()) != 0) return false;
    std::wstring leaf = token_path.substr(expected.size());
    if (leaf.empty() || leaf.find_first_of(L"\\/") != std::wstring::npos) return false;
    std::wstring directory = expected.substr(0, expected.size() - 1);
    HANDLE directory_handle = CreateFileW(
        directory.c_str(), FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (directory_handle == INVALID_HANDLE_VALUE) return false;
    BY_HANDLE_FILE_INFORMATION directory_info{};
    bool safe_directory = GetFileInformationByHandle(directory_handle, &directory_info) &&
        (directory_info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) &&
        !(directory_info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT);
    CloseHandle(directory_handle);
    if (!safe_directory) return false;
    return true;
}

bool load_authorization(const std::wstring &path) {
    std::vector<std::uint8_t> file;
    if (!read_file(path.c_str(), file, 64 * 1024) || file.size() < 8 ||
        std::memcmp(file.data(), "NPA1", 4)) return false;
    std::uint32_t length = 0;
    std::memcpy(&length, file.data() + 4, sizeof(length));
    if (length != file.size() - 8) return false;
    DATA_BLOB encrypted{length, file.data() + 8}, plain{};
    if (!CryptUnprotectData(&encrypted, nullptr, nullptr, nullptr, nullptr,
                            CRYPTPROTECT_UI_FORBIDDEN, &plain)) return false;
    bool okay = plain.cbData > 24 && plain.cbData < kMaxHeader &&
        !std::memcmp(plain.pbData, "Nebula-Account-v1 ", 18);
    if (okay) {
        for (DWORD i = 0; i < plain.cbData; ++i) {
            if (i == 17) {
                if (plain.pbData[i] != 0x20) { okay = false; break; }
            } else if (plain.pbData[i] < 0x21 || plain.pbData[i] > 0x7e) {
                okay = false; break;
            }
        }
    }
    if (okay) {
        DWORD dot = plain.cbData;
        for (DWORD i = 18; i < plain.cbData; ++i) {
            unsigned char value = plain.pbData[i];
            bool base64url = (value >= 'A' && value <= 'Z') ||
                (value >= 'a' && value <= 'z') || (value >= '0' && value <= '9') ||
                value == '-' || value == '_';
            if (value == '.' && dot == plain.cbData) { dot = i; continue; }
            if (!base64url) { okay = false; break; }
        }
        // SteamID64 encodes to 23 unpadded base64url characters; the issued
        // token is exactly 43 URL-safe characters.
        if (dot != 41 || plain.cbData != 85) okay = false;
    }
    if (okay) {
        std::memcpy(g.authorization, plain.pbData, plain.cbData);
        g.authorization[plain.cbData] = 0;
        VirtualLock(g.authorization, sizeof(g.authorization));
    }
    SecureZeroMemory(plain.pbData, plain.cbData);
    LocalFree(plain.pbData);
    return okay;
}

bool resolve_api() {
    g.game = GetModuleHandleW(L"GameAssembly.dll");
    if (!g.game) return false;
    auto domain_get = exported<DomainGet>(g.game, "il2cpp_domain_get");
    auto assemblies = exported<DomainAssemblies>(g.game, "il2cpp_domain_get_assemblies");
    auto assembly_image = exported<AssemblyImage>(g.game, "il2cpp_assembly_get_image");
    auto image_name = exported<ImageName>(g.game, "il2cpp_image_get_name");
    auto class_from_name = exported<ClassFromName>(g.game, "il2cpp_class_from_name");
    auto class_method = exported<ClassMethod>(g.game, "il2cpp_class_get_method_from_name");
    g.invoke = exported<RuntimeInvoke>(g.game, "il2cpp_runtime_invoke");
    g.string_new = exported<StringNewUtf16>(g.game, "il2cpp_string_new_utf16");
    if (!domain_get || !assemblies || !assembly_image || !image_name || !class_from_name ||
        !class_method || !g.invoke || !g.string_new) return false;
    std::size_t count = 0;
    void **list = assemblies(domain_get(), &count);
    if (!list || count > 256) return false;
    void *image = nullptr;
    for (std::size_t i = 0; i < count; ++i) {
        void *candidate = assembly_image(list[i]);
        const char *name = candidate ? image_name(candidate) : nullptr;
        if (name && !std::strcmp(name, "UnityEngine.UnityWebRequestModule.dll")) image = candidate;
    }
    void *klass = image ? class_from_name(image, "UnityEngine.Networking", "UnityWebRequest") : nullptr;
    const void *get = klass ? class_method(klass, "Get", 1) : nullptr;
    g.set_header = klass ? class_method(klass, "SetRequestHeader", 2) : nullptr;
    g.set_redirect_limit = klass ? class_method(klass, "set_redirectLimit", 1) : nullptr;
    if (!get || !g.set_header || !g.set_redirect_limit) return false;
    auto pointer = *static_cast<void *const *>(get);
    if (pointer != reinterpret_cast<std::uint8_t *>(g.game) + kReviewedGetRva) return false;
    g.original_get = reinterpret_cast<GetRequest>(pointer);
    return true;
}

BOOL CALLBACK initialize(PINIT_ONCE, PVOID, PVOID *) {
    std::wstring token_path;
    g.ready = resolve_api() && load_config(token_path) && load_authorization(token_path);
    if (g.ready) NebulaRemote_LoadProfile(g.origin);
    return TRUE;
}

void ensure_initialized() {
    InitOnceExecuteOnce(&g.once, initialize, nullptr, nullptr);
}
}

NPA_EXPORT std::uint32_t NebulaPublicAccess_AbiVersion() { return kAbi; }

NPA_EXPORT void *NebulaPublicAccess_Get(void *managed_url, const void *method_info) {
    ensure_initialized();
    if (!g.original_get) {
        // The PE integration must never target this wrapper unless metadata
        // resolution proves the reviewed original. Returning null fails closed.
        return nullptr;
    }
    std::wstring url;
    if (!managed_text(managed_url, url)) return g.original_get(managed_url, method_info);
    // Remote mode points the reviewed metadata origin at this loopback API.
    // The hash-pinned sidecar must own all listeners before Unity creates the
    // first request. A failed or absent profile returns no request and never
    // falls through to an untrusted local process.
    if (NebulaRemote_IsLoopbackRequest(url) && !NebulaRemote_EnsureReady()) return nullptr;
    void *request = g.original_get(managed_url, method_info);
    if (!request || !g.ready || !exact_origin(url)) return request;
    std::int32_t redirect_limit = 0;
    void *redirect_arguments[]{&redirect_limit};
    void *redirect_exception = nullptr;
    g.invoke(g.set_redirect_limit, request, redirect_arguments, &redirect_exception);
    if (redirect_exception) return request;
    static constexpr std::uint16_t name[] = {
        'A','u','t','h','o','r','i','z','a','t','i','o','n'
    };
    void *header_name = g.string_new(name, static_cast<std::int32_t>(sizeof(name) / sizeof(name[0])));
    int wide_count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, g.authorization, -1,
                                         nullptr, 0);
    if (!header_name || wide_count <= 1 || wide_count > static_cast<int>(kMaxHeader)) return request;
    std::vector<std::uint16_t> wide(static_cast<std::size_t>(wide_count));
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, g.authorization, -1,
                            reinterpret_cast<wchar_t *>(wide.data()), wide_count) != wide_count) return request;
    void *header_value = g.string_new(wide.data(), wide_count - 1);
    if (!header_value) return request;
    void *arguments[]{header_name, header_value};
    void *exception = nullptr;
    g.invoke(g.set_header, request, arguments, &exception);
    // A managed exception leaves the request uncredentialed; the public
    // backend then rejects it. Never retry against a different origin.
    return request;
}

BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_DETACH) {
        SecureZeroMemory(g.authorization, sizeof(g.authorization));
        VirtualUnlock(g.authorization, sizeof(g.authorization));
    }
    return TRUE;
}
