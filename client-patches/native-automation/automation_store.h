#pragma once
#include "store_policy.h"

namespace nac_store {

enum class InvokeResult : std::uint8_t { Started, GuardRejected, ManagedException };

// The future combined helper supplies a thin adapter using its existing exact
// IL2CPP metadata/type/invoke/list/text/desktop/network utilities. Capture()
// must reacquire every Unity object; no pointer may be retained by this module.
struct Host {
    virtual bool capture(Observation &out,const char *&reason) noexcept=0;
    virtual InvokeResult invoke(Callback callback,const char *&reason) noexcept=0;
protected:
    ~Host()=default;
};

struct Result {
    const char *status{"rejected"};
    const char *code{"store_not_started"};
};

class Module {
public:
    Result dispatch(Host &host,Action action,std::uint64_t now,bool purchase_opt_in) noexcept;
    Result service(Host &host,std::uint64_t now) noexcept;
    const Machine &machine() const noexcept{return machine_;}
private:
    Result execute(Host &host,const Step &step) noexcept;
    bool accepted(Callback callback,const Observation &after,const char *&reason) noexcept;
    Machine machine_{};
    std::uint8_t requests_[3]{};
};

}

