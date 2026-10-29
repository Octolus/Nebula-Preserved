#include "social_module.h"

namespace nebula::social_v7 {
namespace {
bool safe_text(std::string_view text) {
  if (text.empty() || text.size() > 160) return false;
  for (unsigned char c : text) if (c < 0x20 || c > 0x7e) return false;
  return true;
}
bool sender_started_only(Action action) {
  return action == Action::FriendRequest || action == Action::Invite ||
         action == Action::InviteAccept || action == Action::ChatSend ||
         action == Action::Talk;
}
bool same_binding(const Binding& a, const Binding& b) {
  return a.valid && b.valid && a.session_hash == b.session_hash &&
         a.local_guid_hash == b.local_guid_hash && a.local_net_id == b.local_net_id &&
         a.manager_instance_id == b.manager_instance_id &&
         a.scene_incarnation_hash == b.scene_incarnation_hash &&
         a.generation_epoch == b.generation_epoch;
}
}

bool Module::common(const Observation& o) const {
  return o.desktop_owned && o.nexus_or_world && o.session_ready && o.network_ready &&
         o.local_identity_exact;
}

void Module::reset() {
  phase_ = Phase::Idle;
  callback_ = Callback::None;
  confirmation_dispatched_ = false;
  request_ = {};
  before_ = {};
}

Result Module::begin(void* owner, const Request& request, std::uint64_t now) {
  if (phase_ != Phase::Idle) return {Phase::Failed, Callback::None, "overlap"};
  if (!owner || request.peer_slot < 1 || request.peer_slot > 2 ||
      request.deadline_ms <= now)
    return {Phase::Failed, Callback::None, "request_guard"};
  if (request.action == Action::ChatSend && !safe_text(request.text))
    return {Phase::Failed, Callback::None, "text_guard"};

  const char* why = "observe";
  Observation observed{};
  if (!host_.observe(owner, request.peer_slot, observed, why) || !common(observed) ||
      !observed.binding.valid)
    return {Phase::Failed, Callback::None, why};
  request_ = request;
  before_ = observed;

  switch (request.action) {
    case Action::Presence:
      phase_ = Phase::Awaiting;
      return {phase_, Callback::None, "observing"};
    case Action::FriendRequest:
      callback_ = Callback::AddFriend;
      if (observed.friend_rel || !observed.peer_present ||
          !observed.space_users_receiver_exact || !observed.selected_model_exact)
        return {Phase::Failed, callback_, "friend_request_authority"};
      break;
    case Action::FriendAccept:
      callback_ = Callback::AcceptFriendNotification;
      if (!observed.friend_notification_exact)
        return {Phase::Failed, callback_, "friend_notification_authority"};
      break;
    case Action::FavoriteOn:
    case Action::FavoriteOff:
      callback_ = Callback::ToggleFavorite;
      if (!observed.friend_rel || !observed.options_receiver_exact ||
          !observed.selected_model_exact ||
          (request.action == Action::FavoriteOn && observed.favorite_rel) ||
          (request.action == Action::FavoriteOff && !observed.favorite_rel))
        return {Phase::Failed, callback_, "favorite_authority"};
      break;
    case Action::BlockOn:
      callback_ = Callback::Block;
      if (!observed.peer_present || !observed.space_users_receiver_exact ||
          !observed.selected_model_exact)
        return {Phase::Failed, callback_, "block_authority"};
      break;
    case Action::BlockOff:
      callback_ = Callback::Remove;
      if (!observed.blocked_rel || !observed.simple_receiver_exact ||
          !observed.selected_model_exact)
        return {Phase::Failed, callback_, "block_remove_authority"};
      break;
    case Action::SilenceOn:
      callback_ = Callback::SelectSilence;
      if (!observed.peer_present || observed.silenced_rel ||
          !observed.remote_receiver_exact)
        return {Phase::Failed, callback_, "silence_authority"};
      break;
    case Action::SilenceOff:
      callback_ = Callback::Remove;
      if (!observed.silenced_rel || !observed.simple_receiver_exact ||
          !observed.selected_model_exact)
        return {Phase::Failed, callback_, "silence_remove_authority"};
      break;
    case Action::Invite:
      callback_ = Callback::Invite;
      if (!observed.friend_rel || !observed.options_receiver_exact ||
          !observed.selected_model_exact)
        return {Phase::Failed, callback_, "invite_authority"};
      break;
    case Action::InviteAccept:
      callback_ = Callback::AcceptInviteNotification;
      if (!observed.invite_notification_exact)
        return {Phase::Failed, callback_, "invite_notification_authority"};
      break;
    case Action::Talk:
      callback_ = Callback::Talk;
      if (!observed.friend_rel || !observed.options_receiver_exact ||
          !observed.selected_model_exact)
        return {Phase::Failed, callback_, "talk_authority"};
      break;
    case Action::ChatSend:
      callback_ = Callback::SendChat;
      if (!observed.private_tab_exact || !observed.input_exact)
        return {Phase::Failed, callback_, "chat_authority"};
      break;
  }

  if (!host_.invoke(owner, callback_, request.peer_slot, request.text, why))
    return {Phase::Failed, callback_, why};
  if (sender_started_only(request.action)) {
    phase_ = Phase::Started;
    return {phase_, callback_, request.action == Action::InviteAccept
      ? "invite_accept_callback_started_travel_unproven"
      : "sender_callback_started_recipient_unproven"};
  }
  phase_ = Phase::Awaiting;
  return {phase_, callback_, "dispatched"};
}

bool Module::complete(const Observation& o) const {
  switch (request_.action) {
    case Action::Presence:
      return o.presence_generation > before_.presence_generation;
    case Action::FriendAccept:
      return o.relation_generation > before_.relation_generation && o.friend_rel;
    case Action::FavoriteOn:
      return o.relation_generation > before_.relation_generation && o.favorite_rel;
    case Action::FavoriteOff:
      return o.relation_generation > before_.relation_generation && !o.favorite_rel;
    case Action::BlockOn:
      return o.relation_generation > before_.relation_generation && o.blocked_rel;
    case Action::BlockOff:
      return o.relation_generation > before_.relation_generation && !o.blocked_rel;
    case Action::SilenceOn:
      return o.relation_generation > before_.relation_generation && o.silenced_rel;
    case Action::SilenceOff:
      return o.relation_generation > before_.relation_generation && !o.silenced_rel;
    case Action::InviteAccept:
      // Accepting an invite intentionally changes scene/manager context. The
      // callback is therefore reported started-only; a fresh, separately
      // receipted operation must prove allocation and target-world readiness.
      return false;
    case Action::Talk:
      return false;
    case Action::FriendRequest:
    case Action::Invite:
    case Action::ChatSend:
      return false;
  }
  return false;
}

Result Module::poll(void* owner, std::uint64_t now) {
  if (phase_ != Phase::Awaiting) return {Phase::Failed, callback_, "not_pending"};
  if (!owner) { phase_ = Phase::Failed; return {phase_, callback_, "owner_guard"}; }
  if (now >= request_.deadline_ms) {
    phase_ = Phase::Failed;
    return {phase_, callback_, "deadline"};
  }
  const char* why = "observe";
  Observation observed{};
  if (!host_.observe(owner, request_.peer_slot, observed, why) || !common(observed)) {
    phase_ = Phase::Failed;
    return {phase_, callback_, why};
  }
  if (!same_binding(before_.binding, observed.binding)) {
    phase_ = Phase::Failed;
    return {phase_, callback_, "operation_binding_changed"};
  }
  if (request_.action == Action::SilenceOn && !confirmation_dispatched_) {
    if (!observed.remote_receiver_exact || !observed.generic_confirmation_exact)
      return {phase_, callback_, "confirmation_pending"};
    if (!host_.invoke(owner, Callback::Confirm, request_.peer_slot, {}, why)) {
      phase_ = Phase::Failed;
      return {phase_, Callback::Confirm, why};
    }
    confirmation_dispatched_ = true;
    callback_ = Callback::Confirm;
    return {phase_, callback_, "confirmation_dispatched"};
  }
  if (complete(observed)) {
    phase_ = Phase::Complete;
    return {phase_, callback_, "complete"};
  }
  return {phase_, callback_, "pending"};
}
}
