#pragma once
#include <cstdint>
#include "resource_selection.h"

namespace nebula_resource_ui {
enum class Action : std::uint8_t {
  SelectCompanion, RemoveCompanion, SelectLocomotion, RemoveLocomotion
};
enum class Phase : std::uint8_t { Idle, Awaiting, Complete, Failed };

struct Binding {
  bool valid{};
  std::uint64_t session_hash{}, local_guid_hash{}, scene_hash{}, generation_epoch{};
  std::uint32_t local_net_id{};
  std::int32_t manager_instance_id{};
};
struct Observation {
  Binding binding{};
  bool current_exact{}, current_empty{};
  std::uint64_t resource_generation{};
};
struct Result { Phase phase{Phase::Idle}; const char *code{"idle"}; };

class Host {
 public:
  virtual ~Host() = default;
  virtual bool capture(Action, bool require_selection, Observation&, nebula_resource_selection::Snapshot&,
                       const char*& reason) noexcept = 0;
  virtual nebula_resource_selection::Result invoke(
      Action, const nebula_resource_selection::Snapshot&, const char*& reason) noexcept = 0;
};

class Module {
 public:
  Result begin(Host&, Action, std::uint64_t now, std::uint64_t deadline) noexcept;
  Result poll(Host&, std::uint64_t now) noexcept;
  void reset() noexcept;
  bool pending() const noexcept { return phase_ == Phase::Awaiting; }
  Phase phase() const noexcept { return phase_; }
  const char *code() const noexcept { return code_; }
  Action action() const noexcept { return action_; }
 private:
  Action action_{Action::SelectCompanion};
  Phase phase_{Phase::Idle};
  Binding binding_{};
  std::uint64_t before_generation_{}, deadline_{};
  const char *code_{"idle"};
};
}
