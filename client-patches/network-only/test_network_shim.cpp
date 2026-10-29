// Run only the actual linked wrapper against local function-pointer fixtures.
// No game libraries, network, UI, filesystem IPC or managed objects are used.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
extern "C" void JoinQueueUpdate(void*,void*);
namespace {
std::uint32_t decision{};
unsigned gates{},drains{};
void* expected{};
std::array<unsigned,4> queue{{1,2,3,4}};
std::uint32_t gate(void* value) noexcept {
    assert(value==expected);++gates;return decision;
}
void public_get() {}
}
extern "C" {
std::uint32_t(*IatJoinReady)(void*) noexcept=gate;
void(*IatPublicGet)()=public_get;
void OriginalProcessTasks(void* value,void* method) {
    assert(value==expected&&method==nullptr);++drains;
}
}
int main() {
    expected=queue.data();const auto original=queue;
    for(auto value:{0u,2u,0xffffffffu}) {
        decision=value;gates=drains=0;
        JoinQueueUpdate(expected,reinterpret_cast<void*>(0x1234));
        assert(gates==1&&drains==0&&queue==original);
    }
    decision=1;gates=drains=0;
    JoinQueueUpdate(expected,reinterpret_cast<void*>(0x1234));
    assert(gates==1&&drains==1&&queue==original);
    JoinQueueUpdate(expected,reinterpret_cast<void*>(0x5678));
    assert(gates==2&&drains==2&&queue==original);
    // The Windows unwinder must undo exactly the wrapper's 0x38 allocation.
    DWORD64 image{};auto function=&JoinQueueUpdate;DWORD64 address{};
    static_assert(sizeof(address)==sizeof(function));std::memcpy(&address,&function,sizeof(address));
    auto entry=RtlLookupFunctionEntry(address,&image,nullptr);
    assert(entry&&image+entry->BeginAddress==address);
    alignas(16)std::array<DWORD64,16> frame{};frame[7]=0x123456789abcdef0ull;
    CONTEXT context{};context.Rip=address+4;context.Rsp=reinterpret_cast<DWORD64>(frame.data());
    void* handler{};DWORD64 establisher{};
    RtlVirtualUnwind(UNW_FLAG_NHANDLER,image,context.Rip,entry,&context,&handler,&establisher,nullptr);
    assert(context.Rip==frame[7]&&context.Rsp==reinterpret_cast<DWORD64>(frame.data())+0x40);
    return 0;
}
