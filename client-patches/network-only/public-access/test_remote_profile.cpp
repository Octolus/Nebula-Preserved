// Exercise the actual profile gate. Never starts a sidecar, game or listener.
#include "NebulaRemoteBootstrap.cpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace fs = std::filesystem;
namespace {
unsigned checks = 0;
void expect(bool value, const char *why) {
    if (!value) throw std::runtime_error(why);
    ++checks;
}
void write(const fs::path &path, const std::string &bytes) {
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!stream) throw std::runtime_error("Cannot write synthetic profile");
}
std::string replace(std::string text, const std::string &from, const std::string &to) {
    const auto position = text.find(from);
    if (position == std::string::npos) throw std::runtime_error("Missing fixture fragment");
    return text.replace(position, from.size(), to);
}
}
int wmain(int argc, wchar_t **argv) {
    try {
        if (argc != 2) throw std::runtime_error("Supply a new disposable profile directory");
        const fs::path root(argv[1]);
        if (!root.is_absolute() || fs::exists(root)) throw std::runtime_error("New absolute output required");
        fs::create_directories(root / "NebulaPreservation");
        if (!SetEnvironmentVariableW(L"LOCALAPPDATA", root.c_str())) throw std::runtime_error("Cannot set fixture profile");
        const fs::path folder = root / "NebulaPreservation";
        const fs::path file = folder / "remote-game.conf";
        const std::wstring origin = L"https://play.example.org:8444";
        const std::string system = "format=nebula-remote-transport-v2\nserver_url=https://play.example.org:8444\ngateway_port=8443\napi_port=38080\nfirst_scene_port=28000\nlast_scene_port=28031\ntrust=system\n";
        auto accepts = [&](const std::string &profile) { write(file, profile); return parse_profile(origin); };
        expect(accepts(system), "System profile without CA must pass");
        expect(!fs::exists(folder / "operator-ca.der"), "System profile must not require a CA file");
        for (const auto &profile : {
            replace(system, "trust=system", "trust=any"),
            replace(system, "transport-v2", "transport-v1"),
            replace(system, "transport-v2", "transport-v3"),
            system + "ca_file=forbidden\n", system + "ca_sha256=forbidden\n",
            system + "trust=system\n", system + "unexpected=x\n",
            system + "\n", system + std::string(1, '\0'),
            replace(system, "trust=system", "trust=system\r"),
            replace(system, "gateway_port=8443", "gateway_port=8444"),
            replace(system, "gateway_port=8443", "gateway_port=08443"),
            replace(system, "api_port=38080", "api_port=38081"),
            replace(system, "last_scene_port=28031", "last_scene_port=28032"),
            replace(system, "play.example.org", "other.example.org"),
            replace(system, "trust=system\n", ""),
        }) expect(!accepts(profile), "Malformed/mixed system profile must fail");
        const std::string ca("synthetic bootstrap hash fixture");
        const fs::path ca_file = folder / "operator-ca.der";
        write(ca_file, ca);
        std::array<std::uint8_t, 32> digest{};
        expect(sha256(std::vector<std::uint8_t>(ca.begin(), ca.end()), digest), "Fixture SHA256");
        const char *hex = "0123456789abcdef";
        std::string pin;
        for (auto byte : digest) { pin += hex[byte >> 4]; pin += hex[byte & 15]; }
        const auto legacy = replace(replace(system, "transport-v2", "transport-v1"),
            "trust=system\n", "ca_file=" + ca_file.u8string() + "\nca_sha256=" + pin + "\n");
        expect(accepts(legacy), "Legacy private-CA profile must still pass");
        expect(!accepts(legacy + "trust=system\n"), "Legacy profile cannot mix system trust");
        expect(!accepts(replace(legacy, "transport-v1", "transport-v2")), "No trust version downgrade");
        write(ca_file, ca + "tampered");
        expect(!accepts(legacy), "Legacy CA pin must detect tampering");
        std::cout << "TOTAL " << checks << " remote profile checks passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
