// Included inside the V16 helper's anonymous namespace after shared helpers.
// All managed pointers are reacquired from the current Pump owner and remain
// stack-local to a single observe/invoke call.
#include "social_module.h"
namespace ns = nebula::social_v7;

char social_session_digest[65]{};
const char* social_status = "idle";
const char* social_code = "social_not_started";

bool social_peer_name(std::uint8_t slot, char out[40]) {
    wchar_t raw[4]{};
    DWORD n = GetEnvironmentVariableW(L"NEBULA_PRESERVATION_TEST_SLOT", raw, 4);
    if (n != 1 || (raw[0] != L'1' && raw[0] != L'2') || slot < 1 || slot > 2 ||
        slot == std::uint8_t(raw[0] - L'0')) return false;
    std::snprintf(out, 40, "[TEST] Preservation Client %u", unsigned(slot));
    return true;
}

std::uint8_t social_other_slot() {
    wchar_t raw[4]{};
    DWORD n = GetEnvironmentVariableW(L"NEBULA_PRESERVATION_TEST_SLOT", raw, 4);
    return n == 1 && raw[0] == L'1' ? 2 : n == 1 && raw[0] == L'2' ? 1 : 0;
}

bool social_roots(void*& manager, void*& social, const char*& reason) {
    manager = singleton(klass(script_image, "", "ManagerInstance"), "_singleton");
    if (!derived_unity(manager, "ManagerInstance")) {
        reason = "social_manager_guard";
        return false;
    }
    social = field<void*>(manager, 0x228);
    if (!typed(social, "SocialManager", "", true)) {
        reason = "social_manager_component_guard";
        return false;
    }
    return true;
}

bool social_fixed_managed_name(std::uint8_t slot, void*& managed, const char*& reason) {
    char expected[40]{};
    if (!social_peer_name(slot, expected)) {
        reason = "social_fixed_slot_guard";
        return false;
    }
    wchar_t wide[40]{};
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, expected, -1, wide, 40);
    if (count <= 1) {
        reason = "social_identity_encoding_guard";
        return false;
    }
    managed = api.string_new_utf16(reinterpret_cast<std::uint16_t*>(wide), count - 1);
    SecureZeroMemory(wide, sizeof(wide));
    if (!managed) {
        reason = "social_identity_string_guard";
        return false;
    }
    return true;
}

bool social_lookup_peer(void* manager, std::uint8_t slot, void*& peer, const char*& reason) {
    peer = nullptr;
    void* memory = field<void*>(manager, 0x2c0);
    if (!typed(memory, "Memory", "Assets.Scripts.Memories")) {
        reason = "social_memory_guard";
        return false;
    }
    void* name = nullptr;
    if (!social_fixed_managed_name(slot, name, reason)) return false;
    std::int32_t platform = 1;
    void* args[] = {name, &platform};
    void* result = nullptr;
    void* target = method(klass(script_image, "Assets.Scripts.Memories", "Memory"),
                          "GetNebulaPlayerByUsername", 2, 0x610940);
    if (!invoke(target, memory, args, result)) {
        reason = "social_peer_lookup_exception";
        return false;
    }
    peer = typed(result, "NebulaPlayer", "", true) ? result : nullptr;
    return true;
}

bool social_selected_model(void* social, std::uint8_t slot, void*& model,
                           std::int32_t& list_type, const char*& reason) {
    model = field<void*>(social, 0x80);
    if (!typed(model, "SocialListEntryModel")) {
        reason = "social_selected_model_guard";
        return false;
    }
    char expected[40]{}, actual[64]{};
    if (!social_peer_name(slot, expected) ||
        !managed_string(field<void*>(model, 0x20), actual, sizeof(actual)) ||
        std::strcmp(actual, expected) || field<std::int32_t>(model, 0x28) != 1) {
        reason = "social_selected_identity_guard";
        return false;
    }
    list_type = field<std::int32_t>(model, 0x2c);
    return true;
}

#include "friend_request_probe.inc"

bool social_active_component(void* component) {
    void* go = component_game_object(component);
    bool active = false;
    return go && active_hierarchy(go, active) && active;
}

void* social_exact_notification(void* chat, std::uint8_t slot, std::int32_t wanted,
                                const char*& reason) {
    // NotificationsManager.Repaint (RVA 0x480c70) clears its rendered
    // ChatEntry list at +0xc8, creates one row per unread NotificationData,
    // and adds each returned row to +0xc8. ChatTab +0x170 is chat messages;
    // ChatTab +0x178 is its inactive entry pool, not notification authority.
    void* notification_manager = field<void*>(chat, 0x28);
    if (!typed(notification_manager, "NotificationsManager", "", true)) {
        reason = "notification_manager_guard";
        return nullptr;
    }
    std::int32_t count = 0;
    void** items = nullptr;
    if (!list_items(field<void*>(notification_manager, 0xc8), count, items, reason) ||
        count < 0 || count > 128) return nullptr;
    char expected[40]{};
    if (!social_peer_name(slot, expected)) {
        reason = "notification_slot_guard";
        return nullptr;
    }
    void* found = nullptr;
    for (std::int32_t i = 0; i < count; ++i) {
        void* row = items[i];
        // ChatEntry.notification is Nullable<NotificationData>: HasValue +0x108,
        // value type +0x110, playerName +0x118, platform +0x120.
        if (!typed(row, "ChatEntry", "", true) || !social_active_component(row) ||
            !field<std::uint8_t>(row, 0x108) || field<std::int32_t>(row, 0x110) != wanted ||
            field<std::int32_t>(row, 0x120) != 1) continue;
        char actual[64]{};
        if (!managed_string(field<void*>(row, 0x118), actual, sizeof(actual)) ||
            std::strcmp(actual, expected)) continue;
        if (found) {
            reason = wanted == 1 ? "friend_notification_ambiguous" :
                                   "invite_notification_ambiguous";
            return nullptr;
        }
        found = row;
    }
    return found;
}

std::uint64_t social_hash_text(const char* text) {
    std::uint64_t hash = 1469598103934665603ULL;
    for (const unsigned char* p = reinterpret_cast<const unsigned char*>(text); *p; ++p) {
        hash ^= *p;
        hash *= 1099511628211ULL;
    }
    return hash;
}

bool social_private_tab(void* chat, std::uint8_t slot, void*& tab,
                        std::uint32_t& messages, std::uint32_t& received,
                        std::uint64_t& receive_signature, const char*& reason) {
    tab = field<void*>(chat, 0xd8);
    if (!typed(tab, "ChatTab", "", true) || !social_active_component(tab)) {
        reason = "chat_tab_guard";
        return false;
    }
    char expected[40]{}, actual[64]{};
    if (!social_peer_name(slot, expected)) {
        reason = "chat_slot_guard";
        return false;
    }
    // Native set_name stores identity in groupName before uppercasing and
    // truncating its UI label. Native OnTalk also matches the canonical value.
    void* get_group = method(klass(script_image, "", "ChatTab"), "get_groupName", 0, 0x479940);
    void* boxed = nullptr;
    if (field<std::int32_t>(tab, 0x168) != 1) {
        reason = "chat_platform_guard";
        return false;
    }
    if (!invoke(get_group, tab, nullptr, boxed) ||
        !managed_string(boxed, actual, sizeof(actual))) {
        reason = "chat_group_name_read_guard";
        return false;
    }
    if (std::strcmp(actual, expected)) {
        reason = "chat_peer_guard";
        return false;
    }
    std::int32_t count = 0;
    void** items = nullptr;
    if (!list_items(field<void*>(tab, 0x170), count, items, reason) || count < 0 || count > 512)
        return false;
    messages = std::uint32_t(count);
    received = 0;
    receive_signature = 0;
    void* get_text = method(klass(script_image, "", "ChatEntry"), "GetText", 0, 0x476480);
    for (std::int32_t i = 0; i < count; ++i) {
        void* row = items[i];
        if (!typed(row, "ChatEntry", "", true) || !social_active_component(row)) continue;
        void* rendered = nullptr;
        char text[512]{};
        if (!invoke(get_text, row, nullptr, rendered) ||
            !managed_string(rendered, text, sizeof(text))) continue;
        if (!std::strstr(text, expected) || !std::strstr(text, "NACSocialV1")) continue;
        ++received;
        receive_signature = social_hash_text(text) ^ (std::uint64_t(i + 1) << 32) ^
                            std::uint64_t(count);
    }
    return true;
}

struct SocialPrivateTabProbe {
    bool tab_exact{}, input_exact{};
    std::int32_t platform{-1}, chat_type{-1};
    const char* reason{"private_chat_probe_unbound"};
};

// Read-only diagnostics. This does not authorize a callback or select a tab.
// No managed pointer, name, GUID or message survives this invocation.
SocialPrivateTabProbe social_private_tab_probe(void* chat, std::uint8_t slot) {
    SocialPrivateTabProbe out{};
    if (!typed(chat, "Chat", "", true)) { out.reason = "chat_guard"; return out; }
    void* active = field<void*>(chat, 0xd8);
    if (typed(active, "ChatTab", "", true)) {
        out.platform = field<std::int32_t>(active, 0x168);
        out.chat_type = field<std::int32_t>(active, 0x190);
    }
    void* tab = nullptr;
    std::uint32_t messages = 0, received = 0;
    std::uint64_t signature = 0;
    const char* why = nullptr;
    out.tab_exact = social_private_tab(chat, slot, tab, messages, received, signature, why);
    void* input = field<void*>(chat, 0xb8);
    out.input_exact = typed(input, "InputField", "UnityEngine.UI", true) &&
                      social_active_component(input);
    out.reason = !out.tab_exact ? (why ? why : "chat_tab_probe_failed") :
                 !out.input_exact ? "chat_input_guard" : "ready";
    return out;
}

bool social_operation_binding(void* owner, void* manager, void* local,
                              ns::Binding& binding, const char*& reason) {
    binding = {};
    char digest[65]{}, guid[257]{}, scene[128]{};
    if (!session_digest(owner, digest) ||
        !managed_string(field<void*>(owner, 0xe8), guid, sizeof(guid)) || !guid[0] ||
        !typed(local, "NetworkIdentity", "Mirror", true) ||
        !active_scene(scene, sizeof(scene)) || !scene[0]) {
        SecureZeroMemory(digest, sizeof(digest));
        SecureZeroMemory(guid, sizeof(guid));
        reason = "social_operation_binding_guard";
        return false;
    }
    void* scene_box = nullptr;
    void* active = method(klass(core_image, "UnityEngine.SceneManagement", "SceneManager"),
                          "GetActiveScene", 0, 0x1bab240);
    if (!::invoke(active, nullptr, nullptr, scene_box) || !readable(scene_box, 0x14)) {
        SecureZeroMemory(digest, sizeof(digest));
        SecureZeroMemory(guid, sizeof(guid));
        reason = "social_scene_binding_guard";
        return false;
    }
    std::int32_t scene_handle = field<std::int32_t>(scene_box, 0x10);
    void* boxed_id = nullptr;
    void* get_id = method(api.object_class(manager), "GetInstanceID", 0, 0x1b8b190);
    std::int32_t manager_id = 0;
    if (!::invoke(get_id, manager, nullptr, boxed_id) || !boxed_int(boxed_id, manager_id) ||
        !manager_id) {
        SecureZeroMemory(digest, sizeof(digest));
        SecureZeroMemory(guid, sizeof(guid));
        reason = "social_manager_incarnation_guard";
        return false;
    }
    binding.session_hash = social_hash_text(digest);
    binding.local_guid_hash = social_hash_text(guid);
    binding.local_net_id = field<std::uint32_t>(local, 0x28);
    binding.manager_instance_id = manager_id;
    binding.scene_incarnation_hash = social_hash_text(scene) ^
        (std::uint64_t(std::uint32_t(scene_handle)) << 32);
    binding.valid = binding.session_hash && binding.local_guid_hash && binding.local_net_id &&
                    binding.scene_incarnation_hash;
    SecureZeroMemory(digest, sizeof(digest));
    SecureZeroMemory(guid, sizeof(guid));
    if (!binding.valid) reason = "social_operation_binding_invalid";
    return binding.valid;
}

void social_advance_generation(std::uint64_t current, std::uint64_t& prior,
                               std::uint64_t& generation, bool& initialized) {
    if (!initialized) {
        prior = current;
        initialized = true;
    } else if (current != prior) {
        prior = current;
        ++generation;
    }
}

struct SocialV7Host final : ns::Host {
    std::uint64_t relation_signature{}, friend_note_signature{}, invite_note_signature{};
    std::uint64_t chat_signature{}, receive_signature{}, presence_signature{};
    std::uint64_t relation_generation{}, friend_note_generation{}, invite_note_generation{};
    std::uint64_t chat_generation{}, receive_generation{}, presence_generation{};
    std::uint64_t binding_signature{}, binding_epoch{};
    bool relation_initialized{}, friend_note_initialized{}, invite_note_initialized{};
    bool chat_initialized{}, receive_initialized{}, presence_initialized{}, binding_initialized{};

    bool observe(void* owner, std::uint8_t slot, ns::Observation& out,
                 const char*& reason) override {
        out = {};
        auto desktop = current_desktop_proof();
        out.desktop_owned = desktop.probe_ok && desktop.matches_session && !desktop.receives_input;
        char scene[64]{}, digest[65]{};
        out.nexus_or_world = active_scene(scene, sizeof(scene));
        out.local_identity_exact = owner && session_digest(owner, digest);
        if (!social_session_digest[0] && out.local_identity_exact)
            std::memcpy(social_session_digest, digest, 65);
        out.local_identity_exact = out.local_identity_exact &&
                                   !std::strcmp(digest, social_session_digest);
        SecureZeroMemory(digest, sizeof(digest));
        void* local = nullptr;
        auto network = observe_network(local);
        out.network_ready = network.ready && network.authenticated && network.connected;
        out.session_ready = out.local_identity_exact && network.local_player_alive &&
                            network.connection_ready;

        void* manager = nullptr;
        void* social = nullptr;
        if (!social_roots(manager, social, reason)) return false;
        ns::Binding binding{};
        if (!social_operation_binding(owner, manager, local, binding, reason)) return false;
        const std::uint64_t binding_signature_now = binding.session_hash ^
            (binding.local_guid_hash << 1) ^ (std::uint64_t(binding.local_net_id) << 17) ^
            (std::uint64_t(std::uint32_t(binding.manager_instance_id)) << 33) ^
            binding.scene_incarnation_hash;
        if (!binding_initialized || binding_signature_now != binding_signature) {
            binding_signature = binding_signature_now;
            binding_initialized = true;
            ++binding_epoch;
            relation_signature = friend_note_signature = invite_note_signature = 0;
            chat_signature = receive_signature = presence_signature = 0;
            relation_generation = friend_note_generation = invite_note_generation = 0;
            chat_generation = receive_generation = presence_generation = 0;
            relation_initialized = friend_note_initialized = invite_note_initialized = false;
            chat_initialized = receive_initialized = presence_initialized = false;
        }
        binding.generation_epoch = binding_epoch;
        out.binding = binding;
        void* peer = nullptr;
        if (!social_lookup_peer(manager, slot, peer, reason)) return false;
        out.peer_present = peer != nullptr;
        if (peer) {
            out.silenced_rel = field<std::uint8_t>(peer, 0xb4) != 0;
            out.blocked_rel = field<std::uint8_t>(peer, 0xb6) != 0;
            out.friend_rel = field<std::uint8_t>(peer, 0xb8) != 0;
            out.favorite_rel = field<std::uint8_t>(peer, 0xb9) != 0;
        }
        void* model = nullptr;
        std::int32_t list_type = -1;
        const char* selected_reason = nullptr;
        out.selected_model_exact = social_selected_model(social, slot, model, list_type,
                                                         selected_reason);
        if (out.selected_model_exact) {
            out.favorite_rel = out.favorite_rel || field<std::uint8_t>(model, 0x18) != 0;
            out.friend_rel = out.friend_rel || list_type == 0;
            out.silenced_rel = out.silenced_rel || list_type == 1;
            out.blocked_rel = out.blocked_rel || list_type == 2;
        }

        void* options = field<void*>(social, 0x28);
        void* simple = field<void*>(social, 0x48);
        void* space_users = field<void*>(social, 0x50);
        out.options_receiver_exact = typed(options, "SocialOptionsMenu", "", true) &&
                                     social_active_component(options);
        out.simple_receiver_exact = typed(simple, "SocialOptionsMenuSimple", "", true) &&
                                    social_active_component(simple);
        out.space_users_receiver_exact = typed(space_users, "SocialOptionsSpaceUsers", "", true) &&
                                         social_active_component(space_users);

        void* interaction = singleton(klass(script_image, "", "InteractionMenu"), "_singleton");
        void* remote = interaction ? field<void*>(interaction, 0x38) : nullptr;
        void* confirmation = interaction ? field<void*>(interaction, 0x40) : nullptr;
        out.remote_receiver_exact = peer && typed(remote, "RemotePlayerMenu", "", true) &&
                                    field<void*>(remote, 0xb0) == peer &&
                                    social_active_component(remote);
        out.generic_confirmation_exact = out.remote_receiver_exact && confirmation &&
                                         social_active_component(confirmation);

        void* chat = field<void*>(manager, 0x150);
        const char* notification_reason = nullptr;
        void* friend_row = typed(chat, "Chat", "", true) ?
            social_exact_notification(chat, slot, 1, notification_reason) : nullptr;
        void* invite_row = typed(chat, "Chat", "", true) ?
            social_exact_notification(chat, slot, 6, notification_reason) : nullptr;
        out.friend_notification_exact = friend_row != nullptr;
        out.invite_notification_exact = invite_row != nullptr;

        void* tab = nullptr;
        std::uint32_t messages = 0, received = 0;
        std::uint64_t received_signature = 0;
        const char* chat_reason = nullptr;
        if (typed(chat, "Chat", "", true) &&
            social_private_tab(chat, slot, tab, messages, received, received_signature, chat_reason)) {
            out.private_tab_exact = true;
            void* input = field<void*>(chat, 0xb8);
            out.input_exact = typed(input, "InputField", "UnityEngine.UI", true) &&
                              social_active_component(input);
            out.private_messages = messages;
            out.received_messages = received;
            out.chat_received_exact = received != 0;
        }

        std::uint64_t relation = (std::uint64_t(out.friend_rel) << 1) |
                                 (std::uint64_t(out.favorite_rel) << 2) |
                                 (std::uint64_t(out.blocked_rel) << 3) |
                                 (std::uint64_t(out.silenced_rel) << 4);
        std::uint64_t chat_state = (std::uint64_t(messages) << 1) |
                                   std::uint64_t(out.private_tab_exact);
        social_advance_generation(relation, relation_signature, relation_generation,
                                  relation_initialized);
        social_advance_generation(out.friend_notification_exact ? 1 : 0,
                                  friend_note_signature, friend_note_generation,
                                  friend_note_initialized);
        social_advance_generation(out.invite_notification_exact ? 1 : 0,
                                  invite_note_signature, invite_note_generation,
                                  invite_note_initialized);
        social_advance_generation(chat_state, chat_signature, chat_generation, chat_initialized);
        social_advance_generation(received_signature, receive_signature, receive_generation,
                                  receive_initialized);
        social_advance_generation(out.peer_present ? 1 : 0, presence_signature,
                                  presence_generation, presence_initialized);
        out.relation_generation = relation_generation;
        out.friend_notification_generation = friend_note_generation;
        out.invite_notification_generation = invite_note_generation;
        out.chat_generation = chat_generation;
        out.chat_receive_generation = receive_generation;
        out.presence_generation = presence_generation;
        return true;
    }

    bool invoke(void* owner, ns::Callback callback, std::uint8_t slot,
                std::string_view text, const char*& reason) override {
        if (!owner) { reason = "social_owner_guard"; return false; }
        char digest[65]{};
        if (!session_digest(owner, digest) || std::strcmp(digest, social_session_digest)) {
            SecureZeroMemory(digest, sizeof(digest));
            reason = "social_session_changed";
            return false;
        }
        SecureZeroMemory(digest, sizeof(digest));
        void* manager = nullptr;
        void* social = nullptr;
        if (!social_roots(manager, social, reason)) return false;
        void* peer = nullptr;
        if (!social_lookup_peer(manager, slot, peer, reason)) return false;

        void* receiver = nullptr;
        void* target = nullptr;
        void* args[1]{};
        bool argument = false;
        void* model = nullptr;
        std::int32_t list_type = -1;
        auto require_model = [&]() {
            return social_selected_model(social, slot, model, list_type, reason);
        };
        if (callback == ns::Callback::AddFriend) {
            receiver = field<void*>(social, 0x50);
            if (!peer || !require_model() || !typed(receiver, "SocialOptionsSpaceUsers", "", true) ||
                !social_active_component(receiver)) { reason = "friend_receiver_guard"; return false; }
            target = method(klass(script_image, "", "SocialOptionsSpaceUsers"),
                            "OnAddFriend", 0, 0x4c9530);
        } else if (callback == ns::Callback::ToggleFavorite) {
            receiver = field<void*>(social, 0x28);
            if (!peer || !require_model() || !typed(receiver, "SocialOptionsMenu", "", true) ||
                !social_active_component(receiver)) { reason = "favorite_receiver_guard"; return false; }
            target = method(klass(script_image, "", "SocialOptionsMenu"),
                            "ToggleFavourite", 0, 0x4c8730);
        } else if (callback == ns::Callback::Remove) {
            if (!require_model() || (list_type != 1 && list_type != 2)) {
                reason = "remove_model_guard";
                return false;
            }
            receiver = field<void*>(social, 0x48);
            if (!typed(receiver, "SocialOptionsMenuSimple", "", true) ||
                !social_active_component(receiver)) { reason = "remove_receiver_guard"; return false; }
            target = method(klass(script_image, "", "SocialOptionsMenuSimple"),
                            "OnRemove", 0, 0x4c59e0);
        } else if (callback == ns::Callback::Block) {
            receiver = field<void*>(social, 0x50);
            if (!peer || !require_model() || !typed(receiver, "SocialOptionsSpaceUsers", "", true) ||
                !social_active_component(receiver)) { reason = "block_receiver_guard"; return false; }
            target = method(klass(script_image, "", "SocialOptionsSpaceUsers"),
                            "OnBlock", 0, 0x4c9d90);
        } else if (callback == ns::Callback::Invite) {
            receiver = field<void*>(social, 0x28);
            void* invite_object = receiver ? field<void*>(receiver, 0x28) : nullptr;
            bool invite_active = false;
            if (!require_model() || list_type != 0 ||
                !typed(receiver, "SocialOptionsMenu", "", true) ||
                !social_active_component(receiver) ||
                !typed(invite_object, "GameObject", "UnityEngine", true) ||
                !active_hierarchy(invite_object, invite_active) || !invite_active) {
                reason = "invite_selected_friend_receiver_guard";
                return false;
            }
            target = method(klass(script_image, "", "SocialOptionsMenu"),
                            "OnInvite", 0, 0x4c6a60);
        } else if (callback == ns::Callback::Talk) {
            receiver = field<void*>(social, 0x28);
            void* talk_object = receiver ? field<void*>(receiver, 0x20) : nullptr;
            bool talk_active = false;
            if (!peer || !require_model() || list_type != 0 ||
                !typed(receiver, "SocialOptionsMenu", "", true) ||
                !social_active_component(receiver) ||
                !typed(talk_object, "GameObject", "UnityEngine", true) ||
                !active_hierarchy(talk_object, talk_active) || !talk_active) {
                reason = "talk_selected_friend_receiver_guard";
                return false;
            }
            target = method(klass(script_image, "", "SocialOptionsMenu"),
                            "OnTalk", 0, 0x4c7700);
        } else if (callback == ns::Callback::SelectSilence || callback == ns::Callback::Confirm) {
            void* interaction = singleton(klass(script_image, "", "InteractionMenu"), "_singleton");
            receiver = interaction ? field<void*>(interaction, 0x38) : nullptr;
            if (!peer || !typed(receiver, "RemotePlayerMenu", "", true) ||
                field<void*>(receiver, 0xb0) != peer || !social_active_component(receiver)) {
                reason = "silence_receiver_guard";
                return false;
            }
            if (callback == ns::Callback::SelectSilence) {
                static std::int32_t option = 2;
                args[0] = &option;
                argument = true;
                target = method(klass(script_image, "", "RemotePlayerMenu"),
                                "OnOptionSelected", 1, 0x483650);
            } else {
                void* confirmation = interaction ? field<void*>(interaction, 0x40) : nullptr;
                if (!confirmation || !social_active_component(confirmation)) {
                    reason = "confirmation_receiver_guard";
                    return false;
                }
                target = method(klass(script_image, "", "RemotePlayerMenu"),
                                "OnConfirm", 0, 0x4834b0);
            }
        } else {
            void* chat = field<void*>(manager, 0x150);
            if (!typed(chat, "Chat", "", true)) { reason = "chat_guard"; return false; }
            if (callback == ns::Callback::AcceptFriendNotification ||
                callback == ns::Callback::AcceptInviteNotification) {
                std::int32_t wanted = callback == ns::Callback::AcceptFriendNotification ? 1 : 6;
                receiver = social_exact_notification(chat, slot, wanted, reason);
                if (!receiver) return false;
                target = method(klass(script_image, "", "ChatEntry"),
                                "OnSubmit", 1, 0x4764f0);
                args[0] = nullptr;
                argument = true;
            } else if (callback == ns::Callback::SendChat) {
                void* tab = nullptr;
                std::uint32_t messages = 0, received = 0;
                std::uint64_t signature = 0;
                if (!social_private_tab(chat, slot, tab, messages, received, signature, reason))
                    return false;
                void* input = field<void*>(chat, 0xb8);
                if (!typed(input, "InputField", "UnityEngine.UI", true) ||
                    !social_active_component(input)) { reason = "chat_input_guard"; return false; }
                wchar_t wide[161]{};
                int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(),
                                                 int(text.size()), wide, 160);
                if (length <= 0) { reason = "chat_text_encoding"; return false; }
                void* value = api.string_new_utf16(reinterpret_cast<std::uint16_t*>(wide), length);
                SecureZeroMemory(wide, sizeof(wide));
                if (!value) { reason = "chat_text_allocation"; return false; }
                void* setter = method(klass(ui_image, "UnityEngine.UI", "InputField"),
                                      "set_text", 1, 0x1c45560);
                void* set_args[] = {value};
                void* ignored = nullptr;
                if (!::invoke(setter, input, set_args, ignored)) {
                    reason = "chat_text_set";
                    return false;
                }
                receiver = chat;
                target = method(klass(script_image, "", "Chat"),
                                "OnMessageWritten", 0, 0x463310);
            }
        }
        if (!receiver || !target) { reason = "social_callback_guard"; return false; }
        void* ignored = nullptr;
        bool ok = ::invoke(target, receiver, argument ? args : nullptr, ignored);
        reason = ok ? "social_callback_started" : "social_managed_exception";
        return ok;
    }
};

SocialV7Host social_host{};
ns::Module social_module{social_host};

struct SocialNotificationTabState {
    bool pending{};
    ns::Binding binding{};
    std::uint64_t deadline{}, generation_before{};
};

SocialNotificationTabState social_notification_tab_state{};
std::uint64_t social_notification_tab_signature{}, social_notification_tab_generation{};
bool social_notification_tab_initialized{};

bool social_same_binding(const ns::Binding& a, const ns::Binding& b) {
    return a.valid && b.valid && a.session_hash == b.session_hash &&
           a.local_guid_hash == b.local_guid_hash && a.local_net_id == b.local_net_id &&
           a.manager_instance_id == b.manager_instance_id &&
           a.scene_incarnation_hash == b.scene_incarnation_hash &&
           a.generation_epoch == b.generation_epoch;
}

#include "social_player_info_netid.inc"

bool social_notifications_owned_identity(void* owner, void* manager, void* local,
                                         const char*& reason) {
    if (GetCurrentThreadId() != thread || !initialized || disabled ||
        !typed(owner, "PS4Info", "", true) ||
        singleton(klass(script_image, "", "PS4Info"), "_singleton") != owner) {
        reason = "notifications_owner_singleton_guard";
        return false;
    }
    void* memory = field<void*>(manager, 0x2c0);
    void* info = memory ? field<void*>(memory, 0x10) : nullptr;
    void* player = info ? field<void*>(info, 0x30) : nullptr;
    if (!typed(local, "NetworkIdentity", "Mirror", true) ||
        !field<std::uint8_t>(local, 0x1a) || !field<std::uint8_t>(local, 0x1b) ||
        !typed(memory, "Memory", "Assets.Scripts.Memories") ||
        !typed(info, "PlayerInfo", "Assets.Scripts.Memories") ||
        !typed(player, "NebulaPlayer", "", true) || !field<std::uint8_t>(player, 0x9c) ||
        field<void*>(player, 0xf8) != local) {
        reason = "notifications_owned_player_guard";
        return false;
    }
    std::uint32_t info_net_id = 0;
    if (!social_player_info_net_id_exact(info, local, info_net_id)) {
        reason = "notifications_player_info_netid_guard";
        return false;
    }
    char owner_guid[257]{}, info_guid[257]{}, player_guid[257]{};
    char account_primary[65]{}, account_session[65]{}, account_name[65]{};
    wchar_t raw[4]{};
    DWORD count = GetEnvironmentVariableW(L"NEBULA_PRESERVATION_TEST_SLOT", raw, 4);
    const bool slot_one = count == 1 && raw[0] == L'1';
    const bool slot_two = count == 1 && raw[0] == L'2';
    const char* expected_account = slot_one ? "local-preservation-test-1" :
                                   slot_two ? "local-preservation-test-2" : nullptr;
    const char* expected_name = slot_one ? "[TEST] Preservation Client 1" :
                                slot_two ? "[TEST] Preservation Client 2" : nullptr;
    bool exact = expected_account && expected_name &&
        managed_string(field<void*>(owner, 0xe8), owner_guid, sizeof(owner_guid)) && owner_guid[0] &&
        managed_string(field<void*>(info, 0x18), info_guid, sizeof(info_guid)) && info_guid[0] &&
        managed_string(field<void*>(player, 0xa0), player_guid, sizeof(player_guid)) && player_guid[0] &&
        !std::strcmp(owner_guid, info_guid) && !std::strcmp(owner_guid, player_guid) &&
        managed_string(field<void*>(owner, 0x28), account_primary, sizeof(account_primary)) &&
        managed_string(field<void*>(owner, 0xd8), account_session, sizeof(account_session)) &&
        managed_string(field<void*>(owner, 0xe0), account_name, sizeof(account_name)) &&
        !std::strcmp(account_primary, expected_account) &&
        !std::strcmp(account_session, expected_account) &&
        !std::strcmp(account_name, expected_name);
    SecureZeroMemory(owner_guid, sizeof(owner_guid));
    SecureZeroMemory(info_guid, sizeof(info_guid));
    SecureZeroMemory(player_guid, sizeof(player_guid));
    SecureZeroMemory(account_primary, sizeof(account_primary));
    SecureZeroMemory(account_session, sizeof(account_session));
    SecureZeroMemory(account_name, sizeof(account_name));
    SecureZeroMemory(raw, sizeof(raw));
    if (!exact) reason = "notifications_fixed_owned_identity_guard";
    return exact;
}

bool social_notifications_tab_observe(void* owner, std::uint8_t peer,
                                      ns::Observation& observation, bool& active,
                                      const char*& reason) {
    active = false;
    void* local = nullptr;
    auto network = observe_network(local);
    if (std::strcmp(nac::network_reason(network), "ready")) {
        reason = "notifications_network_guard";
        return false;
    }
    void* manager = nullptr;
    void* social = nullptr;
    if (!social_roots(manager, social, reason)) return false;
    if (!social_notifications_owned_identity(owner, manager, local, reason)) return false;
    if (!social_host.observe(owner, peer, observation, reason) ||
        !observation.desktop_owned || !observation.nexus_or_world ||
        !observation.session_ready || !observation.network_ready ||
        !observation.local_identity_exact || !observation.binding.valid) return false;
    void* chat = field<void*>(manager, 0x150);
    if (!typed(chat, "Chat", "", true)) {
        reason = "notifications_chat_guard";
        return false;
    }
    void* getter = method(klass(script_image, "", "Chat"),
                          "get_notificationsTab", 0, 0x465520);
    void* tab = nullptr;
    if (!invoke(getter, chat, nullptr, tab) || !typed(tab, "ChatTab", "", true)) {
        reason = "notifications_tab_guard";
        return false;
    }
    void* rect = nullptr;
    void* get_rect = method(klass(script_image, "", "ChatTab"),
                            "get_rectTransform", 0, 0x479b00);
    if (!invoke(get_rect, tab, nullptr, rect) ||
        !typed(rect, "RectTransform", "UnityEngine", true)) {
        reason = "notifications_tab_rect_guard";
        return false;
    }
    void* toolbar = field<void*>(chat, 0x98);
    void* current = field<void*>(chat, 0xd8);
    void* controls = field<void*>(chat, 0x78);
    std::int32_t tab_count = 0;
    void** tabs = nullptr;
    void* notifications_manager = field<void*>(chat, 0x28);
    if (!typed(notifications_manager, "NotificationsManager", "", true) ||
        !typed(toolbar, "ChatToolbar", "", true) ||
        !typed(controls, "Animator", "UnityEngine", true) ||
        !typed(current, "ChatTab", "", true) ||
        !list_items(field<void*>(chat, 0xa0), tab_count, tabs, reason) ||
        tab_count < 1 || tab_count > 64) {
        reason = "notifications_selection_context_guard";
        return false;
    }
    std::int32_t current_matches = 0;
    std::int32_t notification_matches = 0;
    for (std::int32_t i = 0; i < tab_count; ++i) {
        current_matches += tabs[i] == current ? 1 : 0;
        notification_matches += tabs[i] == tab ? 1 : 0;
    }
    if (current_matches != 1 || notification_matches != 1) {
        reason = "notifications_tab_membership_guard";
        return false;
    }
    void* name_getter = method(klass(script_image, "", "ChatTab"), "get_name", 0, 0x479ad0);
    void* boxed_name = nullptr;
    char name[32]{};
    if (field<std::int32_t>(tab, 0x168) != -1 ||
        !invoke(name_getter, tab, nullptr, boxed_name) ||
        !managed_string(boxed_name, name, sizeof(name)) || std::strcmp(name, "NOTIFICATIONS")) {
        reason = "notifications_tab_identity_guard";
        return false;
    }
    active = social_active_component(chat) && social_active_component(toolbar) &&
             field<std::uint8_t>(chat, 0xe0) && field<void*>(chat, 0xd8) == tab &&
             social_active_component(tab);
    social_advance_generation(active ? 1 : 0, social_notification_tab_signature,
                              social_notification_tab_generation,
                              social_notification_tab_initialized);
    return true;
}

void social_notification_tab_reset() { social_notification_tab_state = {}; }

const char* dispatch_social_notifications(void* owner, std::uint64_t now,
                                          std::uint64_t deadline, const char*& status) {
    if (social_module.pending() || social_notification_tab_state.pending) {
        status = "rejected";
        return "social_action_overlap";
    }
    if (deadline <= now) { status = "rejected"; return "notifications_deadline_guard"; }
    std::uint8_t peer = social_other_slot();
    if (!peer) { status = "rejected"; return "social_fixed_slot_guard"; }
    ns::Observation observation{};
    bool active = false;
    const char* reason = "notifications_observe";
    if (!social_notifications_tab_observe(owner, peer, observation, active, reason)) {
        status = "rejected";
        return reason;
    }
    if (active) { status = "ok"; return "notifications_tab_ready"; }
    void* manager = nullptr;
    void* social = nullptr;
    if (!social_roots(manager, social, reason)) { status = "rejected"; return reason; }
    void* chat = field<void*>(manager, 0x150);
    void* getter = method(klass(script_image, "", "Chat"),
                          "get_notificationsTab", 0, 0x465520);
    void* tab = nullptr;
    if (!typed(chat, "Chat", "", true) ||
        !invoke(getter, chat, nullptr, tab) || !typed(tab, "ChatTab", "", true)) {
        status = "rejected";
        return "notifications_receiver_guard";
    }
    void* show = method(klass(script_image, "", "Chat"), "ShowHideChat", 1, 0x4648e0);
    void* callback = method(klass(script_image, "", "Chat"),
                            "OnTabSelected", 1, 0x4639a0);
    void* set_focus = method(klass(script_image, "", "Chat"), "SetFocus", 1, 0x464710);
    if (!show || !callback || !set_focus) {
        status = "rejected";
        return "notifications_callback_method_guard";
    }
    bool hide = false;
    void* hide_args[] = {&hide};
    void* ignored = nullptr;
    if (!invoke(show, chat, hide_args, ignored) || !social_active_component(chat) ||
        !social_active_component(field<void*>(chat, 0x98))) {
        status = "error";
        return "notifications_show_managed_exception";
    }
    void* args[] = {tab}; // reference argument is the managed object directly
    if (!invoke(callback, chat, args, ignored)) {
        status = "error";
        return "notifications_tab_managed_exception";
    }
    bool focus = true;
    void* focus_args[] = {&focus};
    if (!invoke(set_focus, chat, focus_args, ignored)) {
        status = "error";
        return "notifications_focus_managed_exception";
    }
    social_notification_tab_state.pending = true;
    social_notification_tab_state.binding = observation.binding;
    social_notification_tab_state.deadline = deadline;
    social_notification_tab_state.generation_before = social_notification_tab_generation;
    status = "started";
    return "notifications_tab_callback_started";
}

void service_social_notifications(void* owner, std::uint64_t now) {
    if (!social_notification_tab_state.pending) return;
    if (now >= social_notification_tab_state.deadline) {
        social_status = "error";
        social_code = "notifications_tab_deadline";
        social_notification_tab_reset();
        return;
    }
    std::uint8_t peer = social_other_slot();
    ns::Observation observation{};
    bool active = false;
    const char* reason = "notifications_observe";
    if (!peer || !social_notifications_tab_observe(owner, peer, observation, active, reason)) {
        social_status = "error";
        social_code = reason;
        social_notification_tab_reset();
        return;
    }
    if (!social_same_binding(social_notification_tab_state.binding, observation.binding)) {
        social_status = "error";
        social_code = "notifications_tab_binding_changed";
        social_notification_tab_reset();
        return;
    }
    if (active && social_notification_tab_generation >
                  social_notification_tab_state.generation_before) {
        social_status = "ok";
        social_code = "notifications_tab_selected";
        social_notification_tab_reset();
    }
}

bool social_pending() {
    return social_module.pending() || social_notification_tab_state.pending;
}

void service_social(void* owner, std::uint64_t now) {
    if (social_module.pending()) {
        auto result = social_module.poll(owner, now);
        social_status = result.phase == ns::Phase::Complete ? "ok" :
                        result.phase == ns::Phase::Failed ? "error" : "started";
        social_code = result.reason;
        if (result.phase == ns::Phase::Complete || result.phase == ns::Phase::Failed)
            social_module.reset();
    }
    service_social_notifications(owner, now);
}

const char* dispatch_social(void* owner, ns::Action action, std::uint64_t now,
                            std::uint64_t deadline, const char*& status) {
    if (social_pending()) { status = "rejected"; return "social_action_overlap"; }
    std::uint8_t peer = social_other_slot();
    if (!peer) { status = "rejected"; return "social_fixed_slot_guard"; }
    char digest[65]{};
    if (!owner || !session_digest(owner, digest)) {
        status = "rejected";
        return "social_session_guard";
    }
    if (!social_session_digest[0]) std::memcpy(social_session_digest, digest, 65);
    bool same = !std::strcmp(digest, social_session_digest);
    SecureZeroMemory(digest, sizeof(digest));
    if (!same) { status = "rejected"; return "social_session_changed"; }
    std::string_view text = action == ns::Action::ChatSend ?
                            std::string_view("NACSocialV1") : std::string_view{};
    auto result = social_module.begin(owner, {action, peer, text, deadline}, now);
    social_status = result.phase == ns::Phase::Failed ? "rejected" : "started";
    social_code = result.reason;
    status = social_status;
    if (result.phase == ns::Phase::Failed || result.phase == ns::Phase::Started)
        social_module.reset();
    return social_code;
}

void add_social_snapshot(Json& json, void* owner) {
    ns::Observation observation{};
    const char* reason = nullptr;
    std::uint8_t peer = social_other_slot();
    bool ok = peer && owner && social_host.observe(owner, peer, observation, reason);
    SocialFriendRequestProbe friend_probe{};
    bool friend_ready = peer && owner && social_friend_request_probe(owner, peer, friend_probe);
    ns::Observation notification_observation{};
    const char* notification_reason = nullptr;
    bool notification_tab_active = false;
    bool notification_probe_ok = peer && owner && social_notifications_tab_observe(
        owner, peer, notification_observation, notification_tab_active, notification_reason);
    SocialPrivateTabProbe private_probe{};
    if (ok) {
        void* manager = nullptr;
        void* social = nullptr;
        const char* private_reason = nullptr;
        if (social_roots(manager, social, private_reason))
            private_probe = social_private_tab_probe(field<void*>(manager, 0x150), peer);
        else private_probe.reason = private_reason ? private_reason : "private_chat_roots_guard";
    }
    json.append(",\"social\":{");
    json.append("\"probe_ok\":"); json.boolean(ok);
    json.append(",\"reason\":"); json.string(ok ? "ready" : reason ? reason : "social_probe_failed");
    json.append(",\"peer_slot\":"); json.integer(peer);
    json.append(",\"binding_valid\":"); json.boolean(ok && observation.binding.valid);
    json.append(",\"binding_epoch\":"); json.integer(ok ? observation.binding.generation_epoch : 0);
    json.append(",\"local_net_id\":"); json.integer(ok ? observation.binding.local_net_id : 0);
    json.append(",\"manager_instance_id\":"); json.integer(ok ? std::uint32_t(observation.binding.manager_instance_id) : 0);
    json.append(",\"friend\":"); json.boolean(ok && observation.friend_rel);
    json.append(",\"favorite\":"); json.boolean(ok && observation.favorite_rel);
    json.append(",\"blocked\":"); json.boolean(ok && observation.blocked_rel);
    json.append(",\"silenced\":"); json.boolean(ok && observation.silenced_rel);
    json.append(",\"present\":"); json.boolean(ok && observation.peer_present);
    json.append(",\"friend_notification\":"); json.boolean(ok && observation.friend_notification_exact);
    json.append(",\"invite_notification\":"); json.boolean(ok && observation.invite_notification_exact);
    json.append(",\"chat_received_exact\":"); json.boolean(ok && observation.chat_received_exact);
    json.append(",\"private_tab_probe_ok\":"); json.boolean(ok && private_probe.tab_exact);
    json.append(",\"private_tab_probe_reason\":"); json.string(private_probe.reason);
    json.append(",\"private_input_exact\":"); json.boolean(ok && private_probe.input_exact);
    json.append(",\"private_tab_platform\":"); json.integer(private_probe.platform);
    json.append(",\"private_tab_chat_type\":"); json.integer(private_probe.chat_type);
    json.append(",\"private_messages\":"); json.integer(ok ? observation.private_messages : 0);
    json.append(",\"received_messages\":"); json.integer(ok ? observation.received_messages : 0);
    json.append(",\"relation_generation\":"); json.integer(ok ? observation.relation_generation : 0);
    json.append(",\"friend_notification_generation\":"); json.integer(ok ? observation.friend_notification_generation : 0);
    json.append(",\"invite_notification_generation\":"); json.integer(ok ? observation.invite_notification_generation : 0);
    json.append(",\"chat_generation\":"); json.integer(ok ? observation.chat_generation : 0);
    json.append(",\"chat_receive_generation\":"); json.integer(ok ? observation.chat_receive_generation : 0);
    json.append(",\"presence_generation\":"); json.integer(ok ? observation.presence_generation : 0);
    json.append(",\"notifications_probe_ok\":"); json.boolean(notification_probe_ok);
    json.append(",\"notifications_reason\":"); json.string(notification_probe_ok ? "ready" : notification_reason ? notification_reason : "notifications_probe_failed");
    json.append(",\"notifications_tab_active\":"); json.boolean(notification_probe_ok && notification_tab_active);
    json.append(",\"notifications_tab_generation\":"); json.integer(notification_probe_ok ? social_notification_tab_generation : 0);
    json.append(",\"friend_request_probe_ready\":"); json.boolean(friend_ready);
    json.append(",\"friend_request_probe_reason\":"); json.string(friend_probe.reason);
    json.append(",\"friend_request_main_window\":"); json.boolean(friend_probe.inputs.main_window);
    json.append(",\"friend_request_loading_circle\":"); json.boolean(friend_probe.inputs.loading_circle);
    json.append(",\"friend_request_selected_model\":"); json.boolean(friend_probe.inputs.selected_model);
    json.append(",\"friend_request_peer\":"); json.boolean(friend_probe.inputs.peer);
    json.append(",\"friend_request_remote_username\":"); json.boolean(friend_probe.inputs.remote_username);
    json.append(",\"friend_request_remote_platform\":"); json.boolean(friend_probe.inputs.remote_platform);
    json.append(",\"friend_request_not_already_friend\":"); json.boolean(friend_probe.inputs.not_already_friend);
    json.append(",\"friend_request_local_sender\":"); json.boolean(friend_probe.inputs.local_sender);
    json.append(",\"friend_request_tcp_client\":"); json.boolean(friend_probe.inputs.tcp_client);
    json.append(",\"friend_request_tcp_connected\":"); json.boolean(friend_probe.inputs.tcp_connected);
    json.append(",\"pending\":"); json.boolean(social_pending());
    json.append(",\"status\":"); json.string(social_status);
    json.append(",\"code\":"); json.string(social_code);
    json.append("}");
}

enum class SocialNavigate : std::uint8_t { Open, Friends, SpaceUsers, Silenced, Blocked, SelectPeer };

const char* dispatch_social_navigation(SocialNavigate action, const char*& status) {
    void* manager = nullptr;
    void* social = nullptr;
    const char* reason = nullptr;
    if (!social_roots(manager, social, reason)) { status = "rejected"; return reason; }
    void* receiver = nullptr;
    void* target = nullptr;
    if (action == SocialNavigate::Open) {
        receiver = social;
        target = method(klass(script_image, "", "SocialManager"), "OpenSocial", 0, 0x4c5570);
    } else if (action != SocialNavigate::SelectPeer) {
        receiver = field<void*>(social, 0x18);
        if (!typed(receiver, "SocialMainMenu", "", true) || !social_active_component(receiver)) {
            status = "rejected";
            return "social_navigation_menu_guard";
        }
        const char* name = action == SocialNavigate::Friends ? "OnClickFriend" :
                           action == SocialNavigate::SpaceUsers ? "OnClickSpaceUsers" :
                           action == SocialNavigate::Silenced ? "OnClickSilenced" : "OnClickBlocked";
        std::uintptr_t rva = action == SocialNavigate::Friends ? 0x4c1b80 :
                             action == SocialNavigate::SpaceUsers ? 0x4c2150 :
                             action == SocialNavigate::Silenced ? 0x4c1fd0 : 0x4c1a00;
        target = method(klass(script_image, "", "SocialMainMenu"), name, 0, rva);
    } else {
        std::uint8_t slot = social_other_slot();
        char expected[40]{};
        if (!social_peer_name(slot, expected)) { status = "rejected"; return "social_navigation_slot_guard"; }
        void* window = field<void*>(social, 0x20);
        if (!typed(window, "SocialMainWindow", "", true) || !social_active_component(window)) {
            status = "rejected";
            return "social_navigation_window_guard";
        }
        std::int32_t count = 0;
        void** items = nullptr;
        const char* failure = nullptr;
        if (!list_items(field<void*>(window, 0x88), count, items, failure) || count < 0 || count > 256) {
            status = "rejected";
            return failure ? failure : "social_navigation_list_guard";
        }
        void* found = nullptr;
        for (std::int32_t i = 0; i < count; ++i) {
            void* row = items[i];
            if (!typed(row, "SocialEntry", "", true) || field<std::int32_t>(row, 0x48) != 1 ||
                !social_active_component(row)) continue;
            void* text = field<void*>(row, 0x30);
            char actual[64]{};
            if (!typed(text, "Text", "UnityEngine.UI", true) ||
                !managed_string(field<void*>(text, 0xe0), actual, sizeof(actual)) ||
                std::strcmp(actual, expected)) continue;
            if (found) { status = "rejected"; return "social_navigation_peer_ambiguous"; }
            found = row;
        }
        if (!found) { status = "rejected"; return "social_navigation_peer_missing"; }
        receiver = found;
        target = method(klass(script_image, "", "SocialEntry"), "OnClick", 0, 0x4c15f0);
    }
    if (!receiver || !target) { status = "rejected"; return "social_navigation_callback_guard"; }
    void* ignored = nullptr;
    if (!invoke(target, receiver, nullptr, ignored)) {
        status = "error";
        return "social_navigation_managed_exception";
    }
    status = "started";
    return "social_navigation_callback_started";
}
