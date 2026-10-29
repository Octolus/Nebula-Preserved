#pragma once
#include <cstdint>

namespace nebula_resource_navigation {
enum class Action : std::uint8_t {
  PrepareCompanionSelect, PrepareCompanionRemove,
  PrepareLocomotionSelect, PrepareLocomotionRemove
};
enum class Phase : std::uint8_t { Idle, AwaitRoot, AwaitWheel, AwaitSelection, Complete, Failed };
struct Binding {
  bool valid{}; std::uint64_t session_hash{},local_guid_hash{},scene_hash{},generation_epoch{};
  std::uint32_t local_net_id{}; std::int32_t manager_instance_id{};
};
struct Observation {
  Binding binding{}; bool root_visible{},wheel_visible{},target_selected{},target_ready{};
};
struct Result { Phase phase{Phase::Idle}; const char*code{"idle"}; };
class Host {
 public:
  virtual ~Host()=default;
  virtual bool capture(Action,Observation&,const char*&) noexcept=0;
  virtual bool open_root(Action,const char*&) noexcept=0;
  virtual bool open_panel(Action,const char*&) noexcept=0;
  virtual bool select(Action,const char*&) noexcept=0;
};
class Module {
 public:
  Result begin(Host&,Action,std::uint64_t,std::uint64_t) noexcept;
  Result poll(Host&,std::uint64_t) noexcept;
  void reset() noexcept;
  bool pending() const noexcept { return phase_==Phase::AwaitRoot||phase_==Phase::AwaitWheel||phase_==Phase::AwaitSelection; }
 private:
  Action action_{Action::PrepareCompanionSelect}; Phase phase_{Phase::Idle}; Binding binding_{};
  std::uint64_t deadline_{}; const char*code_{"idle"};
};
}
