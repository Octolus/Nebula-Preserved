#pragma once
#include <cstdint>
#include <string_view>

namespace nebula::social_v7 {
enum class Action : std::uint8_t { Presence, FriendRequest, FriendAccept, FavoriteOn, FavoriteOff,
  BlockOn, BlockOff, SilenceOn, SilenceOff, Invite, InviteAccept, Talk, ChatSend };
enum class Callback : std::uint8_t { None, AddFriend, AcceptFriendNotification,
  AcceptInviteNotification, ToggleFavorite, Remove, Block, SelectSilence, Confirm, Invite,
  Talk, SendChat };
enum class Phase : std::uint8_t { Idle, Started, Awaiting, Complete, Failed };

struct Binding {
  bool valid{};
  std::uint64_t session_hash{}, local_guid_hash{}, scene_incarnation_hash{};
  std::uint64_t generation_epoch{};
  std::uint32_t local_net_id{};
  std::int32_t manager_instance_id{};
};

struct Observation {
  Binding binding{};
  bool desktop_owned{}, nexus_or_world{}, session_ready{}, network_ready{}, local_identity_exact{};
  bool selected_model_exact{}, peer_present{};
  bool options_receiver_exact{}, simple_receiver_exact{}, space_users_receiver_exact{};
  bool remote_receiver_exact{}, generic_confirmation_exact{};
  bool friend_notification_exact{}, invite_notification_exact{};
  bool private_tab_exact{}, input_exact{}, chat_received_exact{};
  bool friend_rel{}, favorite_rel{}, blocked_rel{}, silenced_rel{};
  std::uint32_t private_messages{}, received_messages{};
  std::uint64_t relation_generation{}, friend_notification_generation{};
  std::uint64_t invite_notification_generation{}, chat_generation{};
  std::uint64_t chat_receive_generation{}, presence_generation{};
};

struct Request { Action action{}; std::uint8_t peer_slot{}; std::string_view text{};
  std::uint64_t deadline_ms{}; };
struct Result { Phase phase{Phase::Idle}; Callback callback{Callback::None};
  const char* reason{"idle"}; };

class Host {
 public:
  virtual ~Host() = default;
  virtual bool observe(void* current_owner, std::uint8_t peer_slot, Observation& out,
                       const char*& reason) = 0;
  virtual bool invoke(void* current_owner, Callback cb, std::uint8_t peer_slot,
                      std::string_view text, const char*& reason) = 0;
};

class Module {
 public:
  explicit Module(Host& host) : host_(host) {}
  Result begin(void* current_owner, const Request& request, std::uint64_t now_ms);
  Result poll(void* current_owner, std::uint64_t now_ms);
  void reset();
  bool pending() const { return phase_ == Phase::Awaiting; }
 private:
  bool common(const Observation&) const;
  bool complete(const Observation&) const;
  Host& host_;
  Request request_{};
  Observation before_{};
  Phase phase_{Phase::Idle};
  Callback callback_{Callback::None};
  bool confirmation_dispatched_{};
};
}
