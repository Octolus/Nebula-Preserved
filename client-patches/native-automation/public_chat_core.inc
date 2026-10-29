// Include inside the automation helper anonymous namespace after v16_social_core.inc.
// All managed pointers are pump-local; only immutable binding/counters persist.
namespace nebula_public_chat_v2 {
constexpr char kText[] = "NACPublicV1";
struct State { bool pending{}; ns::Binding binding{}; std::uint64_t deadline{}, generation_before{}; };
State open_state{};
std::uint64_t tab_signature{}, tab_generation{}, receive_signature{}, receive_generation{};
bool tab_initialized{}, receive_initialized{};
const char* status = "idle";
const char* code = "public_chat_not_started";
struct CompletionDiagnostic {
    bool chat_active{}, toolbar_active{}, label_active{}, content_active{};
    bool active_tab_exact{}, chat_focused{}, public_type{};
    bool event_system_active{}, input_active{}, selected_exact{};
    bool input_focused{}, input_allow{}, input_should_activate{};
};
CompletionDiagnostic completion{};

bool public_tab(void* chat, void*& tab, const char*& reason) {
    tab = nullptr;
    void* getter = method(klass(script_image, "", "Chat"), "get_publicTab", 0, 0x465570);
    if (!invoke(getter, chat, nullptr, tab) || !typed(tab, "ChatTab", "", true)) {
        reason = "public_tab_guard"; return false;
    }
    std::int32_t count = 0; void** tabs = nullptr;
    if (!list_items(field<void*>(chat, 0xa0), count, tabs, reason) || count < 1 || count > 64)
        return false;
    std::int32_t matches = 0;
    for (std::int32_t i = 0; i < count; ++i) matches += tabs[i] == tab ? 1 : 0;
    void* group_getter = method(klass(script_image, "", "ChatTab"), "get_groupName", 0, 0x479940);
    void* group = nullptr; char value[32]{};
    if (matches != 1 || field<std::int32_t>(tab, 0x190) != 0 ||
        !invoke(group_getter, tab, nullptr, group) ||
        !managed_string(group, value, sizeof(value)) || std::strcmp(value, "Public")) {
        reason = "public_tab_identity_guard"; return false;
    }
    return true;
}

bool callback_context(void* manager, void* chat, void* tab, bool send,
                      void*& input, const char*& reason) {
    input = field<void*>(chat, 0xb8);
    void* rect = nullptr;
    void* get_rect = method(klass(script_image, "", "ChatTab"),
                            "get_rectTransform", 0, 0x479b00);
    void* toolbar = field<void*>(chat, 0x98);
    void* current = field<void*>(chat, 0xd8);
    void* controls = field<void*>(chat, 0x78);
    void* notifications = field<void*>(chat, 0x28);
    std::int32_t count = 0; void** tabs = nullptr;
    if (!invoke(get_rect, tab, nullptr, rect) ||
        !typed(rect, "RectTransform", "UnityEngine", true) ||
        !typed(toolbar, "ChatToolbar", "", true) ||
        !typed(controls, "Animator", "UnityEngine", true) ||
        !typed(notifications, "NotificationsManager", "", true) ||
        !typed(current, "ChatTab", "", true) ||
        !typed(input, "InputField", "UnityEngine.UI", true) ||
        !list_items(field<void*>(chat, 0xa0), count, tabs, reason) || count < 1 || count > 64) {
        reason = "public_selection_context_guard"; return false;
    }
    std::int32_t current_matches = 0, public_matches = 0;
    for (std::int32_t i = 0; i < count; ++i) {
        current_matches += tabs[i] == current ? 1 : 0;
        public_matches += tabs[i] == tab ? 1 : 0;
    }
    if (current_matches != 1 || public_matches != 1) {
        reason = "public_tab_membership_guard"; return false;
    }
    if (!send) return true;
    void* event_system = field<void*>(chat, 0xb0);
    void* tcp = field<void*>(manager, 0x2b8);
    void* memory = field<void*>(manager, 0x2c0);
    void* info = memory ? field<void*>(memory, 0x10) : nullptr;
    void* player = info ? field<void*>(info, 0x30) : nullptr;
    void* interactor = player ? field<void*>(player, 0x50) : nullptr;
    if (!typed(event_system, "EventSystem", "UnityEngine.EventSystems", true) ||
        !typed(tcp, "TCPClient", "TCPs") ||
        !typed(memory, "Memory", "Assets.Scripts.Memories") ||
        !typed(info, "PlayerInfo", "Assets.Scripts.Memories") ||
        !typed(player, "NebulaPlayer", "", true) ||
        !typed(interactor, "NebulaInteractor", "Assets.Scripts.NebulaPlayers", true)) {
        reason = "public_submit_dependency_guard"; return false;
    }
    return true;
}

bool exact_rendered_message(const char* text, const char* expected_name) {
    if (!text || !expected_name || std::strncmp(text, "<color=#", 8)) return false;
    const char* color_end = std::strchr(text + 8, '>');
    if (!color_end || color_end - (text + 8) != 6) return false;
    for (const char* p = text + 8; p != color_end; ++p)
        if (!(('0' <= *p && *p <= '9') || ('a' <= *p && *p <= 'f') ||
              ('A' <= *p && *p <= 'F'))) return false;
    const char* name = color_end + 1;
    const std::size_t expected_length = std::strlen(expected_name);
    if (std::strncmp(name, expected_name, expected_length)) return false;
    const char* suffix = name + expected_length;
    constexpr char close[] = ": </color>";
    return !std::strncmp(suffix, close, sizeof(close) - 1) &&
           !std::strcmp(suffix + sizeof(close) - 1, kText);
}

bool observe(void* owner, ns::Observation& binding_observation, bool& active,
             bool& input_exact, bool& received_exact, std::uint8_t& received_sender,
             const char*& reason) {
    active = input_exact = received_exact = false; received_sender = 0;
    const std::uint8_t peer = social_other_slot();
    if (!peer) { reason = "public_peer_slot_guard"; return false; }
    void* local = nullptr;
    auto network = observe_network(local);
    if (std::strcmp(nac::network_reason(network), "ready")) {
        reason = "public_network_guard"; return false;
    }
    void* manager = nullptr; void* social = nullptr;
    if (!social_roots(manager, social, reason) ||
        !social_notifications_owned_identity(owner, manager, local, reason) ||
        !social_host.observe(owner, peer, binding_observation, reason) ||
        !binding_observation.desktop_owned || !binding_observation.nexus_or_world ||
        !binding_observation.session_ready || !binding_observation.network_ready ||
        !binding_observation.local_identity_exact || !binding_observation.binding.valid) return false;
    void* chat = field<void*>(manager, 0x150); void* tab = nullptr; void* input = nullptr;
    if (!typed(chat, "Chat", "", true) || !public_tab(chat, tab, reason) ||
        !callback_context(manager, chat, tab, false, input, reason)) return false;
    void* label = field<void*>(tab, 0x138);
    void* content = field<void*>(tab, 0x110);
    void* input_go = component_game_object(input);
    void* event_system = field<void*>(chat, 0xb0);
    void* selected_getter = method(klass(ui_image, "UnityEngine.EventSystems", "EventSystem"),
                                   "get_currentSelectedGameObject", 0, 0x4f14f0);
    void* focused_getter = method(klass(ui_image, "UnityEngine.UI", "InputField"),
                                  "get_isFocused", 0, 0x1c441e0);
    void* selected = nullptr;
    void* boxed_focused = nullptr;
    bool focused = false;
    bool content_active = false;
    if (!typed(label, "Text", "UnityEngine.UI", true) ||
        !typed(content, "GameObject", "UnityEngine", true) ||
        !typed(event_system, "EventSystem", "UnityEngine.EventSystems", true) ||
        !typed(input_go, "GameObject", "UnityEngine", true) ||
        !invoke(selected_getter, event_system, nullptr, selected) ||
        !invoke(focused_getter, input, nullptr, boxed_focused) ||
        !boxed_bool(boxed_focused, focused) ||
        !active_hierarchy(content, content_active)) {
        reason = "public_input_completion_guard";
        return false;
    }
    void* event_go = component_game_object(event_system);
    bool event_active = false, input_active = false;
    if (event_go) active_hierarchy(event_go, event_active);
    if (input_go) active_hierarchy(input_go, input_active);
    completion = {
        social_active_component(chat), social_active_component(field<void*>(chat, 0x98)),
        social_active_component(label), content_active, field<void*>(chat, 0xd8) == tab,
        field<std::uint8_t>(chat, 0xe0) != 0, field<std::int32_t>(chat, 0xc4) == 0,
        event_active, input_active, selected == input_go, focused,
        field<std::uint8_t>(input, 0x1c8) != 0,
        field<std::uint8_t>(input, 0x1c9) != 0
    };
    input_exact = completion.input_focused && completion.selected_exact;
    active = completion.chat_active && completion.toolbar_active && completion.label_active &&
             completion.content_active && completion.active_tab_exact && completion.chat_focused &&
             completion.public_type && input_exact;
    social_advance_generation(active ? 1 : 0, tab_signature, tab_generation, tab_initialized);

    std::int32_t count = 0; void** rows = nullptr;
    if (!list_items(field<void*>(tab, 0x170), count, rows, reason) || count < 0 || count > 512)
        return false;
    char expected[40]{};
    if (!social_peer_name(peer, expected)) { reason = "public_peer_slot_guard"; return false; }
    void* get_text = method(klass(script_image, "", "ChatEntry"), "GetText", 0, 0x476480);
    std::uint64_t current = 0; std::uint32_t found = 0;
    for (std::int32_t i = 0; i < count; ++i) {
        void* row = rows[i]; void* rendered = nullptr; char text[512]{};
        if (!typed(row, "ChatEntry", "", true) || !social_active_component(row) ||
            !invoke(get_text, row, nullptr, rendered) || !managed_string(rendered, text, sizeof(text)) ||
            !exact_rendered_message(text, expected)) continue;
        void* get_id = method(api.object_class(row), "GetInstanceID", 0, 0x1b8b190);
        void* boxed_id = nullptr;
        std::int32_t row_id = 0;
        if (!invoke(get_id, row, nullptr, boxed_id) || !boxed_int(boxed_id, row_id) || !row_id) {
            reason = "public_receipt_instance_guard"; return false;
        }
        ++found;
        current ^= social_hash_text(text) ^
                   (std::uint64_t(std::uint32_t(row_id)) << 32) ^ std::uint32_t(row_id);
    }
    if (found > 1) { reason = "public_receipt_ambiguous"; return false; }
    received_exact = found == 1; received_sender = received_exact ? peer : 0;
    social_advance_generation(current, receive_signature, receive_generation, receive_initialized);
    return true;
}

bool pending() { return open_state.pending; }

const char* show(void* owner, std::uint64_t now, std::uint64_t deadline, const char*& outer) {
    if (pending() || social_pending()) { outer = "rejected"; return "public_chat_overlap"; }
    if (deadline <= now) { outer = "rejected"; return "public_chat_deadline_guard"; }
    ns::Observation observation{}; bool active=false,input=false,received=false; std::uint8_t sender=0;
    const char* reason = "public_chat_observe";
    if (!observe(owner, observation, active, input, received, sender, reason)) { outer="rejected"; return reason; }
    if (active) { outer="ok"; status="ok"; code="public_tab_ready"; return code; }
    void* manager=nullptr; void* social=nullptr;
    if (!social_roots(manager,social,reason)) { outer="rejected"; return reason; }
    void* chat=field<void*>(manager,0x150); void* tab=nullptr; void* input_field=nullptr;
    if (!typed(chat,"Chat","",true) || !public_tab(chat,tab,reason) ||
        !callback_context(manager,chat,tab,false,input_field,reason)) { outer="rejected"; return reason; }
    void* show_method=method(klass(script_image,"","Chat"),"ShowHideChat",1,0x4648e0);
    void* select=method(klass(script_image,"","Chat"),"OnTabSelected",1,0x4639a0);
    void* focus_method=method(klass(script_image,"","Chat"),"SetFocus",1,0x464710);
    void* typing_method=method(klass(script_image,"","Chat"),"SetIsTyping",1,0x464840);
    void* input_method=method(klass(script_image,"","Chat"),"SetInputField",1,0x4647b0);
    if (!show_method||!select||!focus_method||!typing_method||!input_method) { outer="rejected"; return "public_callback_guard"; }
    bool hide=false,focus=true,typing=true; std::int32_t space=0; void* ignored=nullptr;
    void* hide_args[]={&hide}; void* tab_args[]={tab}; void* focus_args[]={&focus};
    void* typing_args[]={&typing}; void* input_args[]={&space};
    if (!invoke(show_method,chat,hide_args,ignored) || !social_active_component(chat) ||
        !social_active_component(field<void*>(chat,0x98)) ||
        !invoke(select,chat,tab_args,ignored) || !invoke(focus_method,chat,focus_args,ignored)) {
        outer="error"; return "public_open_managed_exception";
    }
    if (!invoke(typing_method,chat,typing_args,ignored)) {
        outer="error"; return "public_typing_managed_exception";
    }
    bool input_active_after_typing=false;
    void* input_go=component_game_object(input_field);
    if (!input_go || !active_hierarchy(input_go,input_active_after_typing) || !input_active_after_typing) {
        typing=false; invoke(typing_method,chat,typing_args,ignored);
        outer="error"; return "public_typing_visibility_guard";
    }
    if (!invoke(input_method,chat,input_args,ignored)) {
        typing=false; invoke(typing_method,chat,typing_args,ignored);
        outer="error"; return "public_input_managed_exception";
    }
    open_state={true,observation.binding,deadline,tab_generation};
    status="started"; code="public_tab_callback_started"; outer=status; return code;
}

const char* send(void* owner, const char*& outer) {
    if (pending() || social_pending()) { outer="rejected"; return "public_chat_overlap"; }
    ns::Observation observation{}; bool active=false,input_exact=false,received=false; std::uint8_t sender=0;
    const char* reason="public_chat_observe";
    if (!observe(owner,observation,active,input_exact,received,sender,reason) || !active || !input_exact) {
        outer="rejected"; return active ? "public_input_guard" : reason;
    }
    void* manager=nullptr; void* social=nullptr;
    if (!social_roots(manager,social,reason)) { outer="rejected"; return reason; }
    void* chat=field<void*>(manager,0x150); void* tab=nullptr; void* input=nullptr;
    if (!typed(chat,"Chat","",true) || !public_tab(chat,tab,reason) ||
        !callback_context(manager,chat,tab,true,input,reason) || field<void*>(chat,0xd8)!=tab) {
        outer="rejected"; return reason;
    }
    static constexpr std::uint16_t fixed[]={ 'N','A','C','P','u','b','l','i','c','V','1' };
    void* value=api.string_new_utf16(fixed,11);
    void* setter=method(klass(ui_image,"UnityEngine.UI","InputField"),"set_text",1,0x1c45560);
    void* submit=method(klass(script_image,"","Chat"),"OnMessageWritten",0,0x463310);
    void* args[]={value}; void* ignored=nullptr;
    if (!value||!setter||!submit) { outer="rejected"; return "public_send_method_guard"; }
    if (!invoke(setter,input,args,ignored) || !invoke(submit,chat,nullptr,ignored)) {
        outer="error"; return "public_send_managed_exception";
    }
    status="started"; code="sender_callback_started_recipient_unproven"; outer=status; return code;
}

void service(void* owner, std::uint64_t now) {
    if (!open_state.pending) return;
    if (now >= open_state.deadline) {
        status="error";
        if (!completion.active_tab_exact) code="public_tab_selection_deadline";
        else if (!completion.selected_exact) code="public_input_selection_deadline";
        else if (completion.input_should_activate && !completion.input_allow)
            code="public_input_activation_pending_deadline";
        else if (!completion.input_focused) code="public_input_focus_deadline";
        else code="public_tab_state_deadline";
        open_state={}; return;
    }
    ns::Observation observation{}; bool active=false,input=false,received=false; std::uint8_t sender=0;
    const char* reason="public_chat_observe";
    if (!observe(owner,observation,active,input,received,sender,reason)) {
        status="error"; code=reason; open_state={}; return;
    }
    if (!social_same_binding(open_state.binding,observation.binding)) {
        status="error"; code="public_binding_changed"; open_state={}; return;
    }
    if (active && tab_generation > open_state.generation_before) {
        status="ok"; code="public_tab_selected"; open_state={};
    }
}

void snapshot(Json& json, void* owner) {
    ns::Observation observation{}; bool active=false,input=false,received=false; std::uint8_t sender=0;
    const char* reason="public_chat_observe"; bool ok=owner&&observe(owner,observation,active,input,received,sender,reason);
    json.append(",\"public_chat\":{");
    json.append("\"probe_ok\":");json.boolean(ok);
    json.append(",\"reason\":");json.string(ok?"ready":reason?reason:"public_probe_failed");
    json.append(",\"binding_epoch\":");json.integer(ok?observation.binding.generation_epoch:0);
    json.append(",\"public_tab_exact\":");json.boolean(ok);
    json.append(",\"public_tab_active\":");json.boolean(ok&&active);
    json.append(",\"public_input_exact\":");json.boolean(ok&&input);
    json.append(",\"public_tab_generation\":");json.integer(ok?tab_generation:0);
    json.append(",\"public_received_exact\":");json.boolean(ok&&received);
    json.append(",\"public_received_sender_slot\":");json.integer(ok?sender:0);
    json.append(",\"public_received_text\":");if(ok&&received)json.string(kText);else json.append("null");
    json.append(",\"public_received_chat_type\":");if(ok&&received)json.integer(0);else json.append("null");
    json.append(",\"public_receive_generation\":");json.integer(ok?receive_generation:0);
    json.append(",\"completion\":{");
    json.append("\"chat_active\":");json.boolean(completion.chat_active);
    json.append(",\"toolbar_active\":");json.boolean(completion.toolbar_active);
    json.append(",\"label_active\":");json.boolean(completion.label_active);
    json.append(",\"content_active\":");json.boolean(completion.content_active);
    json.append(",\"active_tab_exact\":");json.boolean(completion.active_tab_exact);
    json.append(",\"chat_focused\":");json.boolean(completion.chat_focused);
    json.append(",\"public_type\":");json.boolean(completion.public_type);
    json.append(",\"event_system_active\":");json.boolean(completion.event_system_active);
    json.append(",\"input_active\":");json.boolean(completion.input_active);
    json.append(",\"selected_exact\":");json.boolean(completion.selected_exact);
    json.append(",\"input_focused\":");json.boolean(completion.input_focused);
    json.append(",\"input_allow\":");json.boolean(completion.input_allow);
    json.append(",\"input_should_activate\":");json.boolean(completion.input_should_activate);
    json.append("}");
    json.append(",\"pending\":");json.boolean(open_state.pending);
    json.append(",\"status\":");json.string(status);json.append(",\"code\":");json.string(code);json.append("}");
}
}
