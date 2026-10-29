// Read-only, bounded row diagnostics. Include after public_chat_core.inc.
// No managed state is changed and no row text/name is emitted.
namespace nebula_row_matchers_v1 {
void row(Json& j, void* value, const char* expected, bool notification) {
    bool active = value && social_active_component(value);
    j.append("{\"active\":"); j.boolean(active);
    if (notification) {
        const bool has_value = value && field<std::uint8_t>(value, 0x108);
        char name[96]{}, arguments[256]{};
        const bool name_read = value && managed_string(field<void*>(value, 0x118), name, sizeof(name));
        const bool arguments_read = value && managed_string(field<void*>(value, 0x130), arguments, sizeof(arguments));
        j.append(",\"has_value\":"); j.boolean(has_value);
        j.append(",\"type\":"); j.integer(value ? field<std::int32_t>(value, 0x110) : -1);
        j.append(",\"platform\":"); j.integer(value ? field<std::int32_t>(value, 0x120) : -1);
        j.append(",\"name_read\":"); j.boolean(name_read);
        j.append(",\"name_expected\":"); j.boolean(name_read && !std::strcmp(name, expected));
        j.append(",\"name_length\":"); j.integer(name_read ? std::strlen(name) : 0);
        j.append(",\"arguments_read\":"); j.boolean(arguments_read);
        j.append(",\"arguments_empty\":"); j.boolean(arguments_read && !arguments[0]);
        j.append(",\"arguments_length\":"); j.integer(arguments_read ? std::strlen(arguments) : 0);
    } else {
        void* get_text = method(klass(script_image, "", "ChatEntry"), "GetText", 0, 0x476480);
        void* rendered = nullptr; char text[512]{};
        const bool text_read = value && invoke(get_text, value, nullptr, rendered) &&
                               managed_string(rendered, text, sizeof(text));
        const char* color_end = text_read && !std::strncmp(text, "<color=#", 8) ? std::strchr(text + 8, '>') : nullptr;
        const char* name = color_end ? color_end + 1 : nullptr;
        const std::size_t n = expected ? std::strlen(expected) : 0;
        const char* suffix = name && !std::strncmp(name, expected, n) ? name + n : nullptr;
        j.append(",\"text_read\":"); j.boolean(text_read);
        j.append(",\"text_length\":"); j.integer(text_read ? std::strlen(text) : 0);
        j.append(",\"color_prefix\":"); j.boolean(color_end && color_end - (text + 8) == 6);
        j.append(",\"name_expected\":"); j.boolean(suffix != nullptr);
        constexpr char close[] = ": </color>";
        constexpr std::size_t close_len = sizeof(close) - 1;
        const bool separator_match = suffix && !std::strncmp(suffix, close, close_len);
        j.append(",\"colon_separator\":"); j.boolean(separator_match);
        j.append(",\"message_expected\":");
        j.boolean(separator_match && !std::strcmp(suffix + close_len, nebula_public_chat_v2::kText));
    }
    j.append("}");
}

void snapshot(Json& j, void* owner) {
    (void)owner;
    const char* reason = "roots"; void* manager = nullptr; void* social = nullptr;
    j.append(",\"row_matchers_v1\":{");
    if (!social_roots(manager, social, reason)) {
        j.append("\"probe_ok\":false,\"reason\":"); j.string(reason); j.append("}"); return;
    }
    void* chat = field<void*>(manager, 0x150); const std::uint8_t peer = social_other_slot();
    char expected[40]{};
    if (!typed(chat, "Chat", "", true) || !peer || !social_peer_name(peer, expected)) {
        j.append("\"probe_ok\":false,\"reason\":\"identity\"}"); return;
    }
    j.append("\"probe_ok\":true,\"notification_rows\":[");
    void* notifications = field<void*>(chat, 0x28);
    std::int32_t count = 0; void** items = nullptr;
    if (typed(notifications, "NotificationsManager", "", true) &&
        list_items(field<void*>(notifications, 0xc8), count, items, reason) && count >= 0 && count <= 128) {
        const std::int32_t limit = count < 8 ? count : 8;
        for (std::int32_t i = 0; i < limit; ++i) { if (i) j.append(","); row(j, items[i], expected, true); }
        j.append("],\"notification_count\":"); j.integer(count);
        j.append(",\"notification_truncated\":"); j.boolean(count > limit);
    } else j.append("],\"notification_count\":-1,\"notification_truncated\":false");
    j.append(",\"public_rows\":[");
    void* public_value = nullptr; count = 0; items = nullptr;
    if (nebula_public_chat_v2::public_tab(chat, public_value, reason) &&
        list_items(field<void*>(public_value, 0x170), count, items, reason) && count >= 0 && count <= 512) {
        const std::int32_t limit = count < 8 ? count : 8;
        for (std::int32_t i = 0; i < limit; ++i) { if (i) j.append(","); row(j, items[i], expected, false); }
        j.append("],\"public_count\":"); j.integer(count);
        j.append(",\"public_truncated\":"); j.boolean(count > limit);
    } else j.append("],\"public_count\":-1,\"public_truncated\":false");
    j.append("}");
}
}
