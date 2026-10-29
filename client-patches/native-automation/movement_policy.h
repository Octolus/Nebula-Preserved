#pragma once
#include <array>
#include <cstdint>
#include <cstring>

// No Unity pointers survive a hook call. The host must reacquire and type-check
// these values on the game thread, using the pinned metadata listed in contract.json.
namespace nebula_movement {
using Digest = std::array<std::uint8_t, 32>;
enum class Direction : std::uint32_t { forward=1, backward=2, left=3, right=4 };
enum class Phase { disabled, armed, moving, waiting_idle, completed, cancelled };
struct Snapshot {
    Digest session{}; // SHA-256 of authenticated account+session+instance+scene+generation.
    std::uint64_t generation{}, now_ms{}, fixed_step{};
    std::uint32_t thread_id{}, net_id{};
    std::uintptr_t control{}, pad{}, player_control{}, control_pad{}, singleton_pad{};
    bool exact_profile{}, authenticated{}, world_scene{}, same_instance{};
    bool current_singleton{}, current_local_player{}, identity_owned{}, network_ready{};
    bool input_belongs_to_player{}, input_available{}, initialized{};
    bool occupying{}, controls_blocked{}, movement_blocked{}, manager_block_26e{}, manager_block_270{};
    bool ordinary_idle_observed{}; // host observes original speed==0 and original idle animator.
};
struct Request {
    Digest session{}, nonce{};
    std::uint64_t generation{}, sequence{}, deadline_ms{};
    std::uint32_t fixed_steps{};
    Direction direction{};
};
inline bool nonzero(const Digest &d) {
    std::uint8_t n=0; for(auto b:d)n|=b; return n!=0;
}
inline bool eligible(const Snapshot &s) {
    return s.exact_profile && s.authenticated && s.world_scene && s.same_instance &&
        s.current_singleton && s.current_local_player && s.identity_owned && s.network_ready &&
        s.input_belongs_to_player && s.input_available && s.initialized && !s.occupying &&
        !s.controls_blocked && !s.movement_blocked && !s.manager_block_26e && !s.manager_block_270 &&
        s.thread_id && s.net_id && s.control && s.pad &&
        s.control==s.player_control && s.pad==s.control_pad && s.pad==s.singleton_pad;
}
inline std::uint32_t bits(float value) { std::uint32_t out; std::memcpy(&out,&value,4); return out; }
class Policy {
    Request request_{};
    Phase phase_{Phase::disabled};
    Digest last_nonce_{};
    std::uint64_t last_sequence_{}, first_step_{}, last_step_{}, idle_after_{};
    std::uint32_t main_thread_{}, net_id_{}, requests_{}, steps_{}, mask_{};
    bool have_step_{};
    bool binding(const Snapshot &s) const {
        return s.thread_id==main_thread_ && s.net_id==net_id_ &&
            s.session==request_.session && s.generation==request_.generation;
    }
public:
    Phase phase() const { return phase_; }
    std::uint32_t frames_used() const { return steps_; }
    bool arm(const Request &r,const Snapshot &s,bool authenticated_one_use_command) {
        const auto d=static_cast<std::uint32_t>(r.direction);
        if(!authenticated_one_use_command || !eligible(s) || !nonzero(r.session) || !nonzero(r.nonce) ||
           r.session!=s.session || r.generation!=s.generation || !r.sequence || r.sequence<=last_sequence_ ||
           r.nonce==last_nonce_ || !r.fixed_steps || r.fixed_steps>120 || d<1 || d>4 ||
           r.deadline_ms<=s.now_ms || r.deadline_ms-s.now_ms>3000 || requests_>=4 ||
           phase_==Phase::armed || phase_==Phase::moving || phase_==Phase::waiting_idle) return false;
        request_=r; last_nonce_=r.nonce; last_sequence_=r.sequence; ++requests_;
        main_thread_=s.thread_id; net_id_=s.net_id; steps_=0; mask_=0; have_step_=false;
        first_step_=last_step_=idle_after_=0; phase_=Phase::armed; return true;
    }
    void cancel() { phase_=Phase::cancelled; request_={}; }
    // Called on the owner thread after ordinary Unity work. Completion requires
    // a strictly later fixed step with ORIGINAL locomotion/idle observations.
    void observe(const Snapshot &s) {
        if(s.thread_id!=main_thread_)return;
        if(phase_!=Phase::armed && phase_!=Phase::moving && phase_!=Phase::waiting_idle)return;
        if(!binding(s)||!eligible(s)){cancel();return;}
        if((phase_==Phase::armed||phase_==Phase::moving) && s.now_ms>=request_.deadline_ms) {
            phase_=Phase::waiting_idle; idle_after_=s.fixed_step;
        }
        if(phase_==Phase::waiting_idle && s.fixed_step>idle_after_ && s.ordinary_idle_observed)
            phase_=Phase::completed;
    }
    // Called only by one of four patched movement callsites AFTER its original
    // PadPS4 getter. Site 0/1 are Move V/H, 2/3 are Rotate V/H. Untouched input
    // retains the exact original float bits (including signed zero/NaN).
    std::uint32_t axis(const Snapshot &s,std::uintptr_t control,std::uintptr_t pad,
                       std::uint32_t site,std::uint32_t original_bits) {
        if(s.thread_id!=main_thread_ || phase_==Phase::disabled || phase_==Phase::completed ||
           phase_==Phase::cancelled)return original_bits;
        if(site>3 || !binding(s) || !eligible(s) || control!=s.control || pad!=s.pad) {
            cancel();return original_bits;
        }
        if(phase_==Phase::waiting_idle)return original_bits;
        if(s.now_ms>=request_.deadline_ms) {
            phase_=Phase::waiting_idle;idle_after_=s.fixed_step;return original_bits;
        }
        if(!have_step_ || s.fixed_step!=last_step_) {
            if((have_step_ && s.fixed_step<=last_step_) || site!=0) {cancel();return original_bits;}
            if(steps_>=request_.fixed_steps) {
                phase_=Phase::waiting_idle;idle_after_=last_step_;return original_bits;
            }
            if(!have_step_)first_step_=s.fixed_step;
            last_step_=s.fixed_step;have_step_=true;++steps_;mask_=0;phase_=Phase::moving;
        }
        // Reject duplicate/out-of-order calls; do not turn arbitrary getter
        // traffic into a virtual input channel.
        const std::uint32_t expected=(1u<<site)-1;
        if(mask_!=expected){cancel();return original_bits;}
        mask_|=1u<<site;
        float vertical=0, horizontal=0;
        switch(request_.direction) {
            case Direction::forward:vertical=-1;break;
            case Direction::backward:vertical=1;break;
            case Direction::left:horizontal=-1;break;
            case Direction::right:horizontal=1;break;
        }
        return bits(site==0||site==2 ? vertical : horizontal);
    }
};
} // namespace nebula_movement
