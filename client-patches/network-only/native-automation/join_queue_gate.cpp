// Production networking repair. Independent of automation opt-in, command IPC,
// test identity, foreground windows and OS input. Runs only from queue Update.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <cstdint>
#include <cstring>
#include <cwchar>
#include "movement_profile.h"
#include "join_queue_gate.h"

namespace {
namespace gate=nebula_join_gate;
using gate::Ptr;
struct Api {
    void*(*object_class)(void*);
    const char*(*class_name)(void*);
    const char*(*class_namespace)(void*);
    void*(*class_parent)(void*);
    void*(*class_from_name)(void*,const char*,const char*);
    void*(*class_method)(void*,const char*,int);
    void*(*class_field)(void*,const char*);
    void(*static_get)(void*,void*);
    void*(*invoke)(const void*,void*,void**,void**);
    void*(*domain_get)();
    void**(*assemblies)(void*,std::size_t*);
    void*(*assembly_image)(void*);
    const char*(*image_name)(void*);
    void*(*string_new)(const char*);
};
Api api{};HMODULE game{};void* script{};void* core{};void* mirror{};
DWORD owner_thread{};bool initialized{},failed{},closed{};
gate::Guard guard{};gate::Epoch closed_epoch{};
gate::Statistics stats{};

bool readable(const void* value,std::size_t size) {
    auto at=reinterpret_cast<Ptr>(value);
    if(at<0x10000||!size||at>UINTPTR_MAX-size)return false;
    const auto end=at+size;
    while(at<end){MEMORY_BASIC_INFORMATION info{};
        if(VirtualQuery(reinterpret_cast<void*>(at),&info,sizeof info)!=sizeof info||
           info.State!=MEM_COMMIT||(info.Protect&(PAGE_GUARD|PAGE_NOACCESS))||
           !(info.Protect&(PAGE_READONLY|PAGE_READWRITE|PAGE_WRITECOPY|PAGE_EXECUTE_READ|
              PAGE_EXECUTE_READWRITE|PAGE_EXECUTE_WRITECOPY)))return false;
        auto base=reinterpret_cast<Ptr>(info.BaseAddress);
        if(base>at||base>UINTPTR_MAX-info.RegionSize||base+info.RegionSize<=at)return false;
        at=base+info.RegionSize;
    }return true;
}
template<class T>T field(void* p,std::size_t offset){T out{};auto at=reinterpret_cast<Ptr>(p);
    if(at<=UINTPTR_MAX-offset&&readable(reinterpret_cast<void*>(at+offset),sizeof out))
        std::memcpy(&out,reinterpret_cast<void*>(at+offset),sizeof out);
    return out;}
bool equals(const char* p,const char* text){auto n=std::strlen(text);return readable(p,n+1)&&!std::memcmp(p,text,n+1);}
bool typed(void* p,const char* name,const char* space,bool unity=false,bool derived=false){
    if(!readable(p,unity?0x18:0x10)||(unity&&!field<void*>(p,0x10)))return false;
    void* klass=api.object_class(p);
    for(unsigned i=0;klass&&i<16;++i){
        if(equals(api.class_name(klass),name)&&equals(api.class_namespace(klass),space))return true;
        if(!derived)break;
        klass=api.class_parent(klass);
    }return false;
}
void* klass(void* image,const char* space,const char* name){return image?api.class_from_name(image,space,name):nullptr;}
void* method(void* cl,const char* name,int argc,Ptr expected){
    void* m=cl?api.class_method(cl,name,argc):nullptr;
    return readable(m,sizeof(void*))&&field<Ptr>(m,0)==reinterpret_cast<Ptr>(game)+expected?m:nullptr;
}
bool invoke(void* m,void* self,void** args,void*& result){
    result=nullptr;if(!m)return false;void* error=nullptr;result=api.invoke(m,self,args,&error);return !error;
}
void* singleton(const char* name,Ptr rva){void* result=nullptr;
    return invoke(method(klass(script,"",name),"get_singleton",0,rva),nullptr,nullptr,result)?result:nullptr;}
bool text(void* value,char* output,std::size_t capacity){
    if(!capacity)return false;
    output[0]=0;
    if(!typed(value,"String","System")||!readable(value,0x14))return false;
    auto n=field<std::int32_t>(value,0x10);
    if(n<0||n>512||!readable(value,0x14+std::size_t(n)*2))return false;
    if(!n)return true;
    auto* chars=reinterpret_cast<wchar_t*>(static_cast<char*>(value)+0x14);
    int bytes=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,chars,n,nullptr,0,nullptr,nullptr);
    if(bytes<=0||std::size_t(bytes)>=capacity||
       WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,chars,n,output,bytes,nullptr,nullptr)!=bytes)return false;
    output[bytes]=0;return true;
}
bool instance_id(void* value,std::int32_t& out){void* boxed=nullptr;out=0;
    if(!invoke(method(klass(core,"UnityEngine","Object"),"GetInstanceID",0,0x1b8b190),value,nullptr,boxed)||
       !typed(boxed,"Int32","System")||!readable(boxed,0x14))return false;
    out=field<std::int32_t>(boxed,0x10);return out!=0;
}
bool profile(){
    wchar_t path[32768]{};DWORD length=GetModuleFileNameW(game,path,32768);
    if(!length||length>=32768)return false;
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    BY_HANDLE_FILE_INFORMATION info{};LARGE_INTEGER size{};
    bool ok=GetFileInformationByHandle(file,&info)&&!(info.dwFileAttributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT))&&
        GetFileSizeEx(file,&size)&&size.QuadPart>0&&size.QuadPart<=512ll*1024*1024;
    BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;
    if(ok)ok=BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0&&
        BCryptCreateHash(alg,&hash,nullptr,0,nullptr,0,0)>=0;
    unsigned char buffer[65536]{},digest[32]{};DWORD got=0;std::uint64_t total=0;
    while(ok){if(!ReadFile(file,buffer,sizeof buffer,&got,nullptr)){ok=false;break;}if(!got)break;
        total+=got;if(total>std::uint64_t(size.QuadPart)||BCryptHashData(hash,buffer,got,0)<0){ok=false;break;}}
    if(ok)ok=total==std::uint64_t(size.QuadPart)&&BCryptFinishHash(hash,digest,sizeof digest,0)>=0;
    if(hash)BCryptDestroyHash(hash);
    if(alg)BCryptCloseAlgorithmProvider(alg,0);
    CloseHandle(file);
    char hex[65]{};constexpr char digits[]="0123456789abcdef";
    for(unsigned i=0;i<32;++i){hex[i*2]=digits[digest[i]>>4];hex[i*2+1]=digits[digest[i]&15];}
    SecureZeroMemory(buffer,sizeof buffer);return ok&&!std::strcmp(hex,NEBULA_MOVEMENT_GAMEASSEMBLY_SHA256);
}
template<class T>T exported(const char* name){auto raw=GetProcAddress(game,name);T value{};static_assert(sizeof value==sizeof raw);
    std::memcpy(&value,&raw,sizeof value);return value;}
bool initialize(){
    game=GetModuleHandleW(L"GameAssembly.dll");if(!game||!profile())return false;
#define BIND(field_name,export_name) api.field_name=exported<decltype(api.field_name)>(export_name);if(!api.field_name)return false
    BIND(object_class,"il2cpp_object_get_class");BIND(class_name,"il2cpp_class_get_name");
    BIND(class_namespace,"il2cpp_class_get_namespace");BIND(class_parent,"il2cpp_class_get_parent");
    BIND(class_from_name,"il2cpp_class_from_name");BIND(class_method,"il2cpp_class_get_method_from_name");
    BIND(class_field,"il2cpp_class_get_field_from_name");BIND(static_get,"il2cpp_field_static_get_value");
    BIND(invoke,"il2cpp_runtime_invoke");BIND(domain_get,"il2cpp_domain_get");BIND(assemblies,"il2cpp_domain_get_assemblies");
    BIND(assembly_image,"il2cpp_assembly_get_image");BIND(image_name,"il2cpp_image_get_name");
    BIND(string_new,"il2cpp_string_new");
#undef BIND
    std::size_t count=0;auto assemblies=api.assemblies(api.domain_get(),&count);
    if(!assemblies||count>512||!readable(assemblies,count*sizeof(void*)))return false;
    for(std::size_t i=0;i<count;++i){auto image=api.assembly_image(assemblies[i]);const char* name=image?api.image_name(image):nullptr;
        if(equals(name,"Assembly-CSharp.dll"))script=image;
        if(equals(name,"UnityEngine.CoreModule.dll"))core=image;
        if(equals(name,"Mirror.dll"))mirror=image;
    }
    if(!script||!core||!mirror)return false;
    owner_thread=GetCurrentThreadId();return true;
}
struct Host {
    bool read(Ptr address,void* out,std::size_t n){if(!::readable(reinterpret_cast<void*>(address),n))return false;
        std::memcpy(out,reinterpret_cast<void*>(address),n);return true;}
    bool readable(Ptr address,std::size_t n){return ::readable(reinterpret_cast<void*>(address),n);}
    bool type(Ptr p,const char* name,const char* ns,bool unity){return typed(reinterpret_cast<void*>(p),name,ns,unity);}
    bool text(Ptr p,char* out,std::size_t n){return ::text(reinterpret_cast<void*>(p),out,n);}
    bool context(Ptr queue,gate::Context& out){
        out={};void* q=reinterpret_cast<void*>(queue);
        if(GetCurrentThreadId()!=owner_thread||!typed(q,"ProcessorQueue","Assets.Scripts.TCPs",true))return false;
        void* manager=singleton("ManagerInstance",0x43cdf0);void* owner=singleton("PS4Info",0x423490);
        if(!typed(manager,"ManagerInstance","",true,true)||!typed(owner,"PS4Info","",true)||!::readable(manager,0x2c8))return false;
        void* tcp=field<void*>(manager,0x2b8);
        if(!typed(tcp,"TCPClient","TCPs")||field<void*>(tcp,0x18)!=q||
           !instance_id(manager,out.epoch.manager)||!instance_id(q,out.epoch.queue)||
           !::text(field<void*>(owner,0xe8),out.epoch.guid,sizeof out.epoch.guid)||!out.epoch.guid[0]||
           !::text(field<void*>(manager,0x248),out.epoch.instance,sizeof out.epoch.instance)||!out.epoch.instance[0])return false;
        void* memory=field<void*>(manager,0x2c0);out.memory=reinterpret_cast<Ptr>(memory);
        if(!typed(memory,"Memory","Assets.Scripts.Memories"))return true;
        void* info=field<void*>(memory,0x10);void* player=field<void*>(info,0x30);void* identity=field<void*>(player,0xf8);
        char info_guid[257]{},player_guid[257]{};
        if(!typed(info,"PlayerInfo","Assets.Scripts.Memories")||!typed(player,"NebulaPlayer","",true)||
           !field<std::uint8_t>(player,0x9c)||!typed(identity,"NetworkIdentity","Mirror",true)||
           !field<std::uint8_t>(identity,0x18)||!field<std::uint8_t>(identity,0x1a)||!field<std::uint8_t>(identity,0x1b)||
           !::text(field<void*>(info,0x18),info_guid,sizeof info_guid)||std::strcmp(info_guid,out.epoch.guid)||
           !::text(field<void*>(player,0xa0),player_guid,sizeof player_guid)||std::strcmp(player_guid,out.epoch.guid))return true;
        out.epoch.local_net_id=field<std::uint32_t>(identity,0x28);if(!out.epoch.local_net_id)return true;
        void* network_class=klass(mirror,"Mirror","NetworkClient");
        // Memory can briefly retain its old local while Mirror reconnects.
        // Binding flags on that old object do not establish current transport.
        gate::Transport network{};void* current_local=nullptr;void* connection=nullptr;void* connected=nullptr;
        void* ready_field=network_class?api.class_field(network_class,"ready"):nullptr;
        if(!ready_field||!invoke(method(network_class,"get_isConnected",0,0x128f140),nullptr,nullptr,connected)||
           !typed(connected,"Boolean","System")||
           !invoke(method(network_class,"get_localPlayer",0,0x128f2f0),nullptr,nullptr,current_local)||
           !invoke(method(network_class,"get_connection",0,0x128f0f0),nullptr,nullptr,connection))return true;
        std::uint8_t ready=0;api.static_get(ready_field,&ready);
        if(!typed(connection,"NetworkConnection","Mirror",false,true)||!::readable(connection,0x21))return true;
        network.probe_ok=true;network.connected=field<std::uint8_t>(connected,0x10)!=0;
        network.current_local_identity=reinterpret_cast<Ptr>(current_local);network.ready=ready!=0;
        network.authenticated=field<std::uint8_t>(connection,0x14)!=0;
        network.connection_ready=field<std::uint8_t>(connection,0x20)!=0;
        if(!gate::transport_matches(network,reinterpret_cast<Ptr>(identity)))return true;
        void* spawned_field=network_class?api.class_field(network_class,"spawned"):nullptr;void* spawned=nullptr;
        if(!spawned_field)return true;
        api.static_get(spawned_field,&spawned);
        if(!typed(spawned,"Dictionary`2","System.Collections.Generic"))return true;
        out.spawned=reinterpret_cast<Ptr>(spawned);out.local_ready=true;return true;
    }
    bool known(Ptr memory,const char* guid,bool& yes){
        yes=false;void* value=api.string_new(guid);if(!value)return false;void* args[]={value};void* result=nullptr;
        if(!invoke(method(klass(script,"Assets.Scripts.Memories","Memory"),"ContainsPlayer",1,0x6107c0),
                   reinterpret_cast<void*>(memory),args,result)||!typed(result,"Boolean","System"))return false;
        yes=field<std::uint8_t>(result,0x10)!=0;return true;
    }
    bool close(Ptr queue,const gate::Epoch& epoch){
        gate::Context current{};if(!context(queue,current)||!(current.epoch==epoch))return false;
        void* manager=singleton("ManagerInstance",0x43cdf0);void* tcp=field<void*>(manager,0x2b8);void* result=nullptr;
        if(!typed(tcp,"TCPClient","TCPs")||field<Ptr>(tcp,0x18)!=queue)return false;
        return invoke(method(klass(script,"TCPs","TCPClient"),"Close",0,0x5e7600),tcp,nullptr,result);
    }
};
}

extern "C" __declspec(dllexport) std::uint32_t NebulaAutomation_JoinQueueReady(void* queue) noexcept {
    if(failed)return 0;
    if(!initialized){if(!initialize()){failed=true;stats.reason=5;return 0;}initialized=true;}
    if(GetCurrentThreadId()!=owner_thread){stats.reason=6;return 0;}
    ++stats.calls;
    Host host{};auto value=gate::observe(host,reinterpret_cast<Ptr>(queue));
    const auto now=GetTickCount64();const bool expired=guard.waiting&&guard.epoch==value.epoch&&now>=guard.since&&now-guard.since>=10000;
    const auto decision=guard.step(value,now);
    if(decision==gate::Decision::Ready){if(value.bound)closed=false;++stats.permits;stats.reason=1;return 1;}
    if(decision==gate::Decision::Wait){++stats.holds;stats.reason=2;return 0;}
    ++stats.rejections;stats.reason=expired?4:3;
    if(decision==gate::Decision::Reject&&value.bound&&(!closed||!(closed_epoch==value.epoch))){
        closed_epoch=value.epoch;closed=true;if(host.close(reinterpret_cast<Ptr>(queue),value.epoch))++stats.closed;
    }
    return 0;
}
namespace nebula_join_gate {
void statistics(Statistics& out) noexcept {out={};if(!owner_thread||GetCurrentThreadId()==owner_thread)out=stats;}
}
