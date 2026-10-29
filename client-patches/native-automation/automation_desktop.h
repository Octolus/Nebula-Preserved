#pragma once
#include <windows.h>
#include <cstring>
#include "automation_protocol.h"

namespace nac {
struct DesktopApi {
    HDESK (WINAPI *thread_desktop)(DWORD);
    BOOL (WINAPI *object_info)(HANDLE,int,PVOID,DWORD,LPDWORD);
};
struct DesktopProof { bool probe_ok{},matches_session{},receives_input{}; };
inline DesktopProof desktop_proof(const char *nonce,DWORD thread,const DesktopApi &api) {
    DesktopProof out{};
    if(!nonce_valid(nonce,64)||nonce[64]||!api.thread_desktop||!api.object_info)return out;
    // Borrowed handle: this function must never close or switch it.
    HDESK desktop=api.thread_desktop(thread);if(!desktop)return out;
    wchar_t name[128]{};DWORD needed=0;
    if(!api.object_info(desktop,2,name,sizeof(name),&needed))return out;
    size_t length=0;while(length<128&&name[length])++length;
    if(length==128||needed!=(length+1)*sizeof(wchar_t))return out;
    BOOL receives=FALSE;needed=0;
    if(!api.object_info(desktop,6,&receives,sizeof(receives),&needed)||needed!=sizeof(receives))return out;
    out.probe_ok=true;out.receives_input=receives!=FALSE;
    constexpr wchar_t prefix[]=L"NebulaAuto-";
    constexpr size_t prefix_size=sizeof(prefix)/sizeof(wchar_t)-1;
    if(length!=prefix_size+64||std::memcmp(name,prefix,prefix_size*sizeof(wchar_t)))return out;
    for(size_t i=0;i<64;++i)if(name[prefix_size+i]!=static_cast<unsigned char>(nonce[i]))return out;
    out.matches_session=true;return out;
}
}
