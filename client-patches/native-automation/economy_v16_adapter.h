#pragma once
#include "economy_store_module.h"
#include <cstddef>
#include <cstdint>

namespace nebula_economy_v16 {

// These are internal same-DLL hooks already present in V16 automation.cpp.
// The recipe binds them with thin static adapters; there are no DLL exports,
// runtime symbol lookups, arbitrary method names or caller-controlled RVAs.
struct SharedCore {
    virtual bool context(void *owner,nebula_economy::Context &out) noexcept=0;
    virtual void *singleton(const char *type,const char *field) noexcept=0;
    virtual bool typed(void *object,const char *type,const char *namespc,bool unity) noexcept=0;
    // Only the polymorphic ManagerInstance singleton uses this adapter.
    virtual bool derived_unity(void *object,const char *type,const char *namespc) noexcept=0;
    virtual void *pointer(void *object,std::size_t offset) noexcept=0;
    virtual std::int32_t int32(void *object,std::size_t offset) noexcept=0;
    virtual std::uint8_t uint8(void *object,std::size_t offset) noexcept=0;
    virtual bool exact_string(void *managed,const char *expected) noexcept=0;
    virtual bool list(void *managed,std::int32_t &count,void **&items,const char *&reason) noexcept=0;
    virtual void *game_object(void *component) noexcept=0;
    virtual bool active(void *game_object,bool &value) noexcept=0;
    virtual bool selected(void *event_system,void *&game_object) noexcept=0;
    virtual bool uint_text(void *text,int &value) noexcept=0;
    virtual void *method(const char *type,const char *name,unsigned args,std::uintptr_t rva) noexcept=0;
    virtual bool invoke(void *method,void *receiver,void **args) noexcept=0;
protected:~SharedCore()=default;
};

struct Probe {
    nebula_economy::Observation observation{};
    void *manager{},*shop{},*window{},*wardrobe{},*target_row{};
    unsigned window_kind{};
    const char *reason{"economy_probe_failed"};
};

class Adapter final:public nebula_economy::Host {
public:
    Adapter(SharedCore &core,void *owner,bool offer_wait=false) noexcept:core_(core),owner_(owner),offer_wait_(offer_wait){}
    bool capture(nebula_economy::Route,nebula_economy::Observation&,const char*&) noexcept override;
    nebula_economy::InvokeResult invoke(nebula_economy::Route,nebula_economy::Currency,
                                        nebula_economy::Callback,const char*&) noexcept override;
    bool probe(nebula_economy::Route,Probe&,nebula_economy::Callback last=nebula_economy::Callback::None,
               unsigned before=0) noexcept;
private:
    bool scan(nebula_economy::Route,Probe&,const char *row_class,unsigned kind) noexcept;
    bool exact_offer(nebula_economy::Route,void *row,void *window) noexcept;
    SharedCore &core_;void *owner_{};bool offer_wait_{};nebula_economy::Callback last_{nebula_economy::Callback::None};unsigned before_{};
};

struct SnapshotSink {
    virtual void boolean(const char *key,bool value) noexcept=0;
    virtual void integer(const char *key,std::int64_t value) noexcept=0;
    virtual void string(const char *key,const char *value) noexcept=0;
protected:~SnapshotSink()=default;
};
void snapshot(const nebula_economy::Module&,const Probe&,SnapshotSink&) noexcept;
}
