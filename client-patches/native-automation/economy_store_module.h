#pragma once
#include "economy_store_policy.h"

namespace nebula_economy {
enum class InvokeResult : std::uint8_t { Started,GuardRejected,ManagedException };
struct Host {
    virtual bool capture(Route route,Observation&out,const char*&reason) noexcept=0;
    virtual InvokeResult invoke(Route route,Currency currency,Callback callback,const char*&reason) noexcept=0;
protected: ~Host()=default;
};
struct Result { const char *status; const char *code; };
class Module {
public:
    Result dispatch(Host&,Action,std::uint64_t,bool purchase_opt_in) noexcept;
    Result service(Host&,std::uint64_t) noexcept;
    const Machine&machine()const noexcept{return machine_;}
private:
    Result execute(Host&,Step) noexcept;
    bool accepted(Callback,const Observation&,const char*&) noexcept;
    Machine machine_{}; std::uint8_t attempts_[6]{};
};
}
