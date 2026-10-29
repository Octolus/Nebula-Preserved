// Opt-in main-thread automation. No worker, OS input, arbitrary RVA or memory API.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include "automation_session_path.h"
#include <cmath>
#include "movement_policy.h"
#include "settings_sidebar_policy.h"
#include "join_queue_gate.h"
#include "automation_protocol.h"
#include "automation_files.h"
#include "automation_login.h"
#include "automation_desktop.h"
#include "automation_wardrobe.h"
#include "automation_preset.h"
#include "automation_capture.h"
#include "automation_types.h"
#include "automation_editor_mutation.h"
#include "economy_store_module.h"
#include "economy_v16_adapter.h"
#include "economy_callback_generations.h"
#include "social_module.h"
#include "resource_ui_module.h"
#include "resource_navigation_module.h"

namespace {
constexpr DWORD kMaxPath=1024;
struct Api {
    void *(*object_class)(void*);
    const char *(*class_name)(void*);
    const char *(*class_namespace)(void*);
    void *(*class_parent)(void*);
    void *(*class_from_type)(const void*);
    void *(*class_image)(void*);
    void *(*class_from_name)(void*,const char*,const char*);
    void *(*class_method)(void*,const char*,int);
    const void *(*method_return_type)(const void*);
    void *(*class_field)(void*,const char*);
    void (*static_get)(void*,void*);
    void *(*invoke)(const void*,void*,void**,void**);
    const void *(*class_type)(void*);
    void *(*type_object)(const void*);
    void *(*domain_get)();
    void **(*assemblies)(void*,size_t*);
    void *(*assembly_image)(void*);
    const char *(*image_name)(void*);
    void *(*string_new_utf16)(const std::uint16_t*,std::int32_t);
};
Api api{};
HMODULE game{};
DWORD thread{};
bool initialized{},disabled{},background_requested{},login_invoked{};
bool store_purchase_configured{};
bool preset_pending{};
bool preset_loading_seen{};
bool remove_pending{},remove_completion_observed{},remove_dispatched{};
bool save_pending{},save_completion_observed{},save_seen_active{};
bool save_input_text_probe_ok{},save_input_read_only_probe_ok{},save_input_line_type_probe_ok{};
bool save_input_initial_empty{},save_input_read_only{};
nac::FrameCaptureState frame_capture_state{};
nebula_economy::Module economy_module{};
const char *economy_status="idle",*economy_code="economy_not_started";
char economy_session_digest[65]{};
uint64_t started{},last_poll{},pumps{},input_bytes{},output_bytes{};
uint64_t preset_deadline{};
uint32_t previous{};
uint32_t preset_phase{};
uint32_t remove_phase{},save_phase{},remove_requests{},save_requests{};
uint32_t head_named_matches{},head_active_matches{},head_compatible_matches{};
uint32_t hat_named_matches{},hat_active_matches{},hat_compatible_matches{};
int32_t remove_pre_assets{},remove_pre_children{};
int32_t save_input_initial_length{-1},save_input_line_type{-1};
char nonce[65]{};
char preset_target[65]{};
char remove_session_digest[65]{},save_session_digest[65]{},save_target[17]{};
char observed_names_digest[65]{},observed_names[32][65]{};
uint32_t observed_names_count{};uint64_t observed_names_at{};bool observed_names_truncated{};
const char *preset_last_code="idle";
const char *remove_last_code="idle",*save_last_code="idle";
const char *save_input_probe_reason="not_probed";
const char *head_scan_reason="not_scanned",*hat_scan_reason="not_scanned";
uint64_t remove_deadline{},save_deadline{};
wchar_t directory[kMaxPath]{};
void *script_image{},*core_image{},*ui_image{},*mirror_image{};

template<class T> T exported(const char *name) {
    FARPROC raw=GetProcAddress(game,name); T out{};
    static_assert(sizeof(out)==sizeof(raw)); std::memcpy(&out,&raw,sizeof(out)); return out;
}
bool readable(const void *p,size_t size) {
    uintptr_t begin=reinterpret_cast<uintptr_t>(p);
    if(begin<0x10000||!size||begin>UINTPTR_MAX-size) return false;
    uintptr_t end=begin+size;
    while(begin<end) {
        MEMORY_BASIC_INFORMATION info{};
        if(VirtualQuery(reinterpret_cast<void*>(begin),&info,sizeof(info))!=sizeof(info)||
           info.State!=MEM_COMMIT||(info.Protect&(PAGE_GUARD|PAGE_NOACCESS))||
           !(info.Protect&(PAGE_READONLY|PAGE_READWRITE|PAGE_WRITECOPY|PAGE_EXECUTE_READ|
                         PAGE_EXECUTE_READWRITE|PAGE_EXECUTE_WRITECOPY))) return false;
        auto base=reinterpret_cast<uintptr_t>(info.BaseAddress);
        if(base>begin||base>UINTPTR_MAX-info.RegionSize||base+info.RegionSize<=begin) return false;
        begin=base+info.RegionSize;
    }
    return true;
}
template<class T> T field(void *owner,size_t offset) {
    T out{}; auto p=reinterpret_cast<uintptr_t>(owner);
    if(p<=UINTPTR_MAX-offset&&readable(reinterpret_cast<void*>(p+offset),sizeof(T)))
        std::memcpy(&out,reinterpret_cast<void*>(p+offset),sizeof(T));
    return out;
}
bool equal_name(const char *p,const char *expected) {
    auto n=std::strlen(expected); return readable(p,n+1)&&!std::memcmp(p,expected,n+1);
}
bool typed(void *p,const char *name,const char *ns="",bool unity=false) {
    if(!readable(p,unity?0x18:0x10)) return false;
    void *klass=api.object_class(p);
    return klass&&equal_name(api.class_name(klass),name)&&equal_name(api.class_namespace(klass),ns)&&
           (!unity||field<void*>(p,0x10));
}
bool runtime_class_matches(void *cl,const char *name,const char *ns) {
    return cl&&equal_name(api.class_name(cl),name)&&equal_name(api.class_namespace(cl),ns);
}
bool derived(void *p,const char *name,const char *ns="",bool unity=false) {
    if(!readable(p,unity?0x18:0x10)||(unity&&!field<void*>(p,0x10)))return false;
    void *cl=api.object_class(p);
    return nac::class_is_or_derives(cl,name,ns,api.class_parent,runtime_class_matches);
}
bool derived_unity(void *p,const char *name,const char *ns="") {return derived(p,name,ns,true);}
bool managed_string(void *p,char *out,size_t capacity) {
    out[0]=0;
    if(!readable(p,0x14)) return false;
    int32_t count=field<int32_t>(p,0x10);
    if(count<0||count>256||!readable(static_cast<char*>(p)+0x14,size_t(count)*2+2)) return false;
    int n=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,reinterpret_cast<wchar_t*>(static_cast<char*>(p)+0x14),count,
                              out,int(capacity-1),nullptr,nullptr);
    if(count&&n<=0) return false;
    out[n]=0; return true;
}
void *klass(void *image,const char *ns,const char *name) { return image?api.class_from_name(image,ns,name):nullptr; }
void *method(void *cl,const char *name,int count,uintptr_t expected) {
    void *m=cl?api.class_method(cl,name,count):nullptr;
    return readable(m,8)&&field<uintptr_t>(m,0)==reinterpret_cast<uintptr_t>(game)+expected?m:nullptr;
}
bool invoke(void *m,void *owner,void **args,void *&out) {
    out=nullptr;
    if(!m) return false;
    void *exception=nullptr;
    out=api.invoke(m,owner,args,&exception);
    // The exported runtime boundary catches managed exceptions. Never rethrow,
    // stringify the exception, or call arbitrary methods to describe it.
    return exception==nullptr;
}
void *singleton(void *cl,const char *name) {
    void *f=cl?api.class_field(cl,name):nullptr; void *out=nullptr;
    if(f) api.static_get(f,&out);
    return out;
}
bool path_for(wchar_t *out,const wchar_t *name) {
    return swprintf(out,kMaxPath,L"%ls\\%ls",directory,name)>0;
}
// The desktop handle is borrowed from the current pump thread and is never
// closed, switched, focused, or used for input. The exact nonce-named,
// non-input desktop proof is required again for every frame request.
nac::DesktopProof current_desktop_proof() {
    HMODULE user=GetModuleHandleW(L"user32.dll");nac::DesktopApi desktop_api{};
    if(user) {
        FARPROC raw=GetProcAddress(user,"GetThreadDesktop");std::memcpy(&desktop_api.thread_desktop,&raw,sizeof(raw));
        raw=GetProcAddress(user,"GetUserObjectInformationW");std::memcpy(&desktop_api.object_info,&raw,sizeof(raw));
    }
    return nac::desktop_proof(nonce,GetCurrentThreadId(),desktop_api);
}
bool initialize(void *owner) {
    initialized=true; started=GetTickCount64(); thread=GetCurrentThreadId();
    wchar_t mode[4]{},wide_nonce[66]{};
    if(GetEnvironmentVariableW(L"NEBULA_AUTOMATION",mode,4)!=1||mode[0]!=L'1'||mode[1]||
       GetEnvironmentVariableW(L"NEBULA_AUTOMATION_NONCE",wide_nonce,66)!=64) return false;
    wchar_t purchase_mode[4]{};
    store_purchase_configured=GetEnvironmentVariableW(
        L"NEBULA_AUTOMATION_ALLOW_LOCAL_PURCHASE",purchase_mode,4)==1&&
        purchase_mode[0]==L'1'&&!purchase_mode[1];
    for(unsigned i=0;i<64;++i) { if(wide_nonce[i]>127) return false; nonce[i]=char(wide_nonce[i]); }
    if(!nac::nonce_valid(nonce,64)) return false;
    DWORD n=GetEnvironmentVariableW(L"NEBULA_AUTOMATION_DIR",directory,kMaxPath);
    if(!n||n>=kMaxPath-64||directory[1]!=L':') return false;
    wchar_t absolute[kMaxPath]{},private_path[kMaxPath]{};
    if(GetFullPathNameW(directory,kMaxPath,absolute,nullptr)!=n||std::wcscmp(directory,absolute)) return false;
    game=GetModuleHandleW(L"GameAssembly.dll");
    DWORD module_path_count=game?GetModuleFileNameW(game,private_path,kMaxPath):0;
    if(!module_path_count||module_path_count>=kMaxPath) return false;
    wchar_t test_slot[4]{};
    DWORD test_slot_count=GetEnvironmentVariableW(L"NEBULA_PRESERVATION_TEST_SLOT",test_slot,4);
    const wchar_t* exact_test_slot=test_slot_count==1&&(test_slot[0]==L'1'||test_slot[0]==L'2')&&!test_slot[1]?test_slot:nullptr;
    if(!nebula_release_v3::session_path_allowed(private_path,directory,exact_test_slot)) return false;
    // Reject reparse points at every directory component, including ancestors.
    std::wcscpy(absolute,directory);
    for(size_t i=3;;++i) if(!absolute[i]||absolute[i]==L'\\') {
        wchar_t save=absolute[i]; absolute[i]=0; DWORD attr=GetFileAttributesW(absolute); absolute[i]=save;
        if(attr==INVALID_FILE_ATTRIBUTES||!(attr&FILE_ATTRIBUTE_DIRECTORY)||(attr&FILE_ATTRIBUTE_REPARSE_POINT)) return false;
        if(!save) break;
    }
#define API(member,export_name) api.member=exported<decltype(api.member)>(export_name); if(!api.member) return false
    API(object_class,"il2cpp_object_get_class"); API(class_name,"il2cpp_class_get_name");
    API(class_namespace,"il2cpp_class_get_namespace"); API(class_image,"il2cpp_class_get_image");
    API(class_parent,"il2cpp_class_get_parent"); API(class_from_type,"il2cpp_class_from_type");
    API(class_from_name,"il2cpp_class_from_name"); API(class_method,"il2cpp_class_get_method_from_name");
    API(method_return_type,"il2cpp_method_get_return_type");
    API(class_field,"il2cpp_class_get_field_from_name"); API(static_get,"il2cpp_field_static_get_value");
    API(invoke,"il2cpp_runtime_invoke"); API(class_type,"il2cpp_class_get_type"); API(type_object,"il2cpp_type_get_object");
    API(domain_get,"il2cpp_domain_get"); API(assemblies,"il2cpp_domain_get_assemblies");
    API(assembly_image,"il2cpp_assembly_get_image"); API(image_name,"il2cpp_image_get_name");
    API(string_new_utf16,"il2cpp_string_new_utf16");
#undef API
    if(!typed(owner,"PS4Info","",true)) return false;
    script_image=api.class_image(api.object_class(owner));
    size_t count=0; void **assemblies=api.assemblies(api.domain_get(),&count);
    if(!assemblies||count>256||!readable(assemblies,count*sizeof(void*))) return false;
    for(size_t i=0;i<count;++i) {
        void *image=api.assembly_image(assemblies[i]); const char *name=image?api.image_name(image):nullptr;
        if(equal_name(name,"UnityEngine.CoreModule.dll")) core_image=image;
        if(equal_name(name,"UnityEngine.UI.dll")) ui_image=image;
        if(equal_name(name,"Mirror.dll")) mirror_image=image;
    }
    return core_image&&script_image&&ui_image&&mirror_image;
}

bool exact_response_array(void *response,int32_t expected,void **&items) {
    items=nullptr;
    if(!response||!runtime_class_matches(api.object_class(response),"String[]","System")||
       !readable(response,0x20)||field<int32_t>(response,0x18)!=expected||expected<=0||expected>16||
       !readable(static_cast<char*>(response)+0x20,size_t(expected)*sizeof(void*))) return false;
    items=reinterpret_cast<void**>(static_cast<char*>(response)+0x20);
    for(int32_t i=0;i<expected;++i)
        if(!items[i]||!runtime_class_matches(api.object_class(items[i]),"String","System"))return false;
    return true;
}
bool response_text(void *value,char *out,size_t capacity,bool nonempty=true) {
    return managed_string(value,out,capacity)&&(!nonempty||out[0]);
}
bool canonical_uint32_text(void *value) {
    char text[32]{};if(!response_text(value,text,sizeof(text)))return false;
    if(text[0]=='0'&&text[1])return false;
    uint64_t n=0;
    for(const unsigned char *p=reinterpret_cast<const unsigned char*>(text);*p;++p) {
        if(*p<'0'||*p>'9')return false;
        n=n*10+(*p-'0');
        if(n>0xffffffffULL)return false;
    }
    return true;
}
bool managed_json_object(void *value) {
    if(!value||!runtime_class_matches(api.object_class(value),"String","System")||!readable(value,0x14))return false;
    int32_t count=field<int32_t>(value,0x10);
    if(count<2||count>1024*1024||!readable(static_cast<char*>(value)+0x14,size_t(count)*2))return false;
    uint16_t first{},last{};
    std::memcpy(&first,static_cast<char*>(value)+0x14,sizeof(first));
    std::memcpy(&last,static_cast<char*>(value)+0x14+size_t(count-1)*2,sizeof(last));
    return first=='{'&&last=='}';
}
bool current_response_owner(void *&owner) {
    owner=nullptr;
    if(!initialized||disabled||GetCurrentThreadId()!=thread||!script_image)return false;
    void *cl=klass(script_image,"","PS4Info");owner=singleton(cl,"_singleton");
    return typed(owner,"PS4Info","",true);
}
bool response_guid_matches(void *owner,void *value) {
    char expected[257]{},actual[257]{};
    return response_text(field<void*>(owner,0xe8),expected,sizeof(expected))&&
        response_text(value,actual,sizeof(actual))&&!std::strcmp(expected,actual);
}
bool valid_shop_info_generation(void *response) {
    void *owner=nullptr,**items=nullptr;if(!current_response_owner(owner)||!exact_response_array(response,6,items))return false;
    char token[8]{},account[257]{},name[257]{};
    if(!response_text(items[0],token,sizeof(token))||std::strcmp(token,"true")||
       !response_guid_matches(owner,items[1])||!response_text(items[2],account,sizeof(account))||
       !response_text(items[3],name,sizeof(name))||!canonical_uint32_text(items[4])||
       !canonical_uint32_text(items[5]))return false;
    void *shop=field<void*>(owner,0x1a8);
    return shop&&readable(shop,0x50)&&field<void*>(shop,0x38)&&field<void*>(shop,0x40)&&field<void*>(shop,0x48);
}
bool valid_purchases_generation(void *response) {
    void *owner=nullptr,**items=nullptr;if(!current_response_owner(owner)||!exact_response_array(response,3,items))return false;
    char token[8]{};
    if(!response_text(items[0],token,sizeof(token))||std::strcmp(token,"true")||
       !response_guid_matches(owner,items[1])||!managed_json_object(items[2]))return false;
    return field<void*>(owner,0x240);
}

bool set_background() {
    void *m=method(klass(core_image,"UnityEngine","Application"),"set_runInBackground",1,0x1b65a00);
    bool value=true; void *args[]={&value}; void *out=nullptr;
    if(!invoke(m,nullptr,args,out)) return false;
    background_requested=true; return true;
}
bool account_hash(void *owner,char out[65]) {
    char raw[1025]{};
    if(!managed_string(field<void*>(owner,0xd8),raw,sizeof(raw))) return false;
    BCRYPT_ALG_HANDLE alg{}; unsigned char digest[32]{};
    if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0) return false;
    NTSTATUS status=BCryptHash(alg,nullptr,0,reinterpret_cast<PUCHAR>(raw),ULONG(std::strlen(raw)),digest,32);
    BCryptCloseAlgorithmProvider(alg,0);
    SecureZeroMemory(raw,sizeof(raw)); if(status<0) return false;
    constexpr char hex[]="0123456789abcdef";
    for(unsigned i=0;i<32;++i) { out[2*i]=hex[digest[i]>>4];out[2*i+1]=hex[digest[i]&15]; }
    out[64]=0; return true;
}
bool session_digest(void *owner,char out[65]) {
    char account[1025]{},session[1025]{};out[0]=0;
    if(!managed_string(field<void*>(owner,0xd8),account,sizeof(account))||!account[0]||
       !managed_string(field<void*>(owner,0xe8),session,sizeof(session))||!session[0]) {
        SecureZeroMemory(account,sizeof(account));SecureZeroMemory(session,sizeof(session));return false;
    }
    BCRYPT_ALG_HANDLE alg{};BCRYPT_HASH_HANDLE hash{};DWORD object_size=0,got=0;
    unsigned char object[512]{},digest[32]{},separator=0;
    bool okay=BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0&&
        BCryptGetProperty(alg,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&object_size),sizeof(object_size),&got,0)>=0&&
        object_size<=sizeof(object)&&BCryptCreateHash(alg,&hash,object,object_size,nullptr,0,0)>=0&&
        BCryptHashData(hash,reinterpret_cast<PUCHAR>(account),ULONG(std::strlen(account)),0)>=0&&
        BCryptHashData(hash,&separator,1,0)>=0&&
        BCryptHashData(hash,reinterpret_cast<PUCHAR>(session),ULONG(std::strlen(session)),0)>=0&&
        BCryptFinishHash(hash,digest,sizeof(digest),0)>=0;
    if(hash)BCryptDestroyHash(hash);
    if(alg)BCryptCloseAlgorithmProvider(alg,0);
    SecureZeroMemory(account,sizeof(account));SecureZeroMemory(session,sizeof(session));SecureZeroMemory(object,sizeof(object));
    if(!okay)return false;
    constexpr char hex[]="0123456789abcdef";
    for(unsigned i=0;i<32;++i){out[2*i]=hex[digest[i]>>4];out[2*i+1]=hex[digest[i]&15];}
    out[64]=0;SecureZeroMemory(digest,sizeof(digest));return true;
}
struct Json {
    char data[16384]{}; size_t size{}; bool valid{true};
    void append(const char *text) { size_t n=std::strlen(text); if(n>=sizeof(data)-size){valid=false;return;} std::memcpy(data+size,text,n+1);size+=n; }
    void integer(uint64_t value) {char b[32];std::snprintf(b,sizeof(b),"%llu",static_cast<unsigned long long>(value));append(b);}
    void string(const char *text) {append("\"");for(const unsigned char *p=reinterpret_cast<const unsigned char*>(text);*p;++p){char b[8]{};if(*p=='"'||*p=='\\'){b[0]='\\';b[1]=char(*p);}else if(*p<32)std::snprintf(b,sizeof(b),"\\u%04x",unsigned(*p));else b[0]=char(*p);append(b);}append("\"");}
    void boolean(bool value){append(value?"true":"false");}
};
bool active_scene(char *out,size_t capacity) {
    out[0]=0;void *box=nullptr;
    void *m=method(klass(core_image,"UnityEngine.SceneManagement","SceneManager"),"GetActiveScene",0,0x1bab240);
    if(!invoke(m,nullptr,nullptr,box)||!readable(box,0x14))return false;
    int32_t handle=field<int32_t>(box,0x10);void *args[]={&handle};
    m=method(klass(core_image,"UnityEngine.SceneManagement","Scene"),"GetNameInternal",1,0x1bac5d0);
    return invoke(m,nullptr,args,box)&&managed_string(box,out,capacity);
}
nac::LoginState observe_login(void *owner,void *&login,void *&target) {
    nac::LoginState s{};char scene[1025]{},session[1025]{};
    s.scene_login=active_scene(scene,sizeof(scene))&&!std::strcmp(scene,"Login");
    s.current_owner=singleton(api.object_class(owner),"_singleton")==owner;
    void *cl=klass(script_image,"","MANAGERLogin");
    login=singleton(cl,"_singleton");
    s.alive=typed(login,"MANAGERLogin","",true)&&readable(login,0xf1);
    s.session_ready=managed_string(field<void*>(owner,0xe8),session,sizeof(session))&&session[0];
    SecureZeroMemory(session,sizeof(session));
    s.pressed=s.alive&&field<uint8_t>(login,0xf0);
    s.steam_ready=typed(field<void*>(owner,0x238),"SteamManager");
    void *loader=singleton(klass(script_image,"","ScreenLoader"),"instance");
    s.loader_ready=typed(loader,"ScreenLoader","",true)&&typed(field<void*>(loader,0x20),"SpinCircle","",true);
    target=method(cl,"onClickLogin",0,0x6e6270);s.method_ready=target;
    s.invoked=login_invoked;return s;
}
const char *start_login(void *owner,const char *&status) {
    void *login=nullptr,*target=nullptr;
    auto state=observe_login(owner,login,target);const char *reason=nac::login_reason(state);
    if(std::strcmp(reason,"ready")){status="rejected";return reason;}
    login_invoked=true; // Preserve one-shot even if the original callback throws.
    auto result=nac::dispatch_login(state,target,login,api.invoke);
    login_invoked=state.invoked;
    if(result==nac::LoginResult::Exception){status="error";return "login_callback_exception";}
    if(result!=nac::LoginResult::Started){status="rejected";return "login_dispatch_guard";}
    if(!typed(login,"MANAGERLogin","",true)||!field<uint8_t>(login,0xf0)) {
        status="error";return "login_callback_did_not_accept";
    }
    status="started";return "native_login_callback_dispatched";
}
nac::NetworkState observe_network(void *&local) {
    nac::NetworkState s{};local=nullptr;
    void *cl=klass(mirror_image,"Mirror","NetworkClient");
    void *connected=method(cl,"get_isConnected",0,0x128f140);
    void *player=method(cl,"get_localPlayer",0,0x128f2f0);
    void *connection=method(cl,"get_connection",0,0x128f0f0);
    void *ready=cl?api.class_field(cl,"ready"):nullptr;
    if(!connected||!player||!connection||!ready)return s;
    void *box=nullptr,*transport=nullptr;
    // The original getter initializes its own static class before ready is read.
    if(!invoke(connected,nullptr,nullptr,box)||!typed(box,"Boolean","System")||!readable(box,0x11))return s;
    s.connected=field<uint8_t>(box,0x10)!=0;
    uint8_t ready_value=0;api.static_get(ready,&ready_value);s.ready=ready_value!=0;
    if(!invoke(player,nullptr,nullptr,local)||!invoke(connection,nullptr,nullptr,transport))return {};
    s.local_player_alive=typed(local,"NetworkIdentity","Mirror",true)&&field<uint8_t>(local,0x1a);
    if(transport&&!derived(transport,"NetworkConnection","Mirror"))return {};
    s.authenticated=transport&&readable(transport,0x15)&&field<uint8_t>(transport,0x14);
    s.connection_ready=transport&&readable(transport,0x21)&&field<uint8_t>(transport,0x20);
    s.probe_ok=true;return s;
}
bool store_phase_pending();
#include "movement_native_core.h"
bool ascii_preset(void *managed,char out[65]) {
    char value[257]{};
    if(!managed_string(managed,value,sizeof(value)))return false;
    size_t length=std::strlen(value);
    if(!length||length>64)return false;
    for(size_t i=0;i<length;++i)if(static_cast<unsigned char>(value[i])<32||static_cast<unsigned char>(value[i])>126)return false;
    std::memcpy(out,value,length+1);return true;
}
struct PresetTiles {
    bool probe_ok{},menu_active{},loading_active{},names_truncated{};
    uint32_t count{},name_count{},matches{};
    char names[32][65]{};
    void *match{};
    const char *scan_reason="not_scanned";
};
bool boxed_bool(void *value,bool &out);
bool game_object_active(void *object,bool &active) {
    void *method_info=method(klass(core_image,"UnityEngine","GameObject"),"get_activeSelf",0,0x1b87b30),*boxed=nullptr;
    return typed(object,"GameObject","UnityEngine",true)&&method_info&&invoke(method_info,object,nullptr,boxed)&&boxed_bool(boxed,active);
}
bool boxed_int(void *value,int32_t &out) {
    if(!typed(value,"Int32","System")||!readable(value,0x14))return false;
    out=field<int32_t>(value,0x10);return true;
}
bool boxed_exact_return_int(void *value,const void *method_info,int32_t &out) {
    if(!value||!method_info||!readable(value,0x14))return false;
    const void *return_type=api.method_return_type(method_info);
    void *return_class=return_type?api.class_from_type(return_type):nullptr;
    if(!nac::exact_return_box_class(api.object_class(value),return_class))return false;
    out=field<int32_t>(value,0x10);return true;
}
bool boxed_bool(void *value,bool &out) {
    if(!typed(value,"Boolean","System")||!readable(value,0x11))return false;
    out=field<uint8_t>(value,0x10)!=0;return true;
}
bool list_items(void *list,int32_t &count,void **&items,const char *&failure) {
    count=0;items=nullptr;
    if(!readable(list,0x20)){failure="list_header_unavailable";return false;}
    count=field<int32_t>(list,0x18);void *array=field<void*>(list,0x10);
    if(count<0||count>256){failure="list_count_invalid";return false;}
    if(!readable(array,0x20)){failure="list_array_header_unavailable";return false;}
    int32_t capacity=field<int32_t>(array,0x18);
    // A valid closed preset menu has an authored empty ListPresets. Preserve
    // header/capacity validation, but do not ask readable() to validate a
    // zero-byte span (it deliberately rejects size==0).
    bool span=count&&readable(static_cast<char*>(array)+0x20,size_t(count)*sizeof(void*));
    if(!nac::preset_list_layout_valid(count,capacity,span)){failure="list_layout_invalid";return false;}
    items=reinterpret_cast<void**>(static_cast<char*>(array)+0x20);return true;
}
bool object_name(void *object,char *out,size_t capacity) {
    void *m=method(klass(core_image,"UnityEngine","Object"),"get_name",0,0x1b8c010),*value=nullptr;
    return object&&invoke(m,object,nullptr,value)&&managed_string(value,out,capacity);
}
bool active_hierarchy(void *object,bool &active) {
    void *m=method(klass(core_image,"UnityEngine","GameObject"),"get_activeInHierarchy",0,0x1b87af0),*box=nullptr;
    return typed(object,"GameObject","UnityEngine",true)&&invoke(m,object,nullptr,box)&&boxed_bool(box,active);
}
void *component(void *object,void *image,const char *ns,const char *name) {
    if(!typed(object,"GameObject","UnityEngine",true))return nullptr;
    void *target=klass(image,ns,name);const void *raw=target?api.class_type(target):nullptr;
    void *type=raw?api.type_object(raw):nullptr,*out=nullptr;
    void *m=method(klass(core_image,"UnityEngine","GameObject"),"GetComponent",1,0x1b87620),*args[]={type};
    return type&&invoke(m,object,args,out)?out:nullptr;
}
void *component_game_object(void *value) {
    void *m=method(klass(core_image,"UnityEngine","Component"),"get_gameObject",0,0x1b85ed0),*out=nullptr;
    return value&&invoke(m,value,nullptr,out)&&typed(out,"GameObject","UnityEngine",true)?out:nullptr;
}
struct DirectNamedObject {
    void *object{};uint32_t matches{},active_matches{},compatible_matches{};
    const char *reason="not_scanned";
};
DirectNamedObject find_named_direct_child(void *parent,const char *target,bool require_active) {
    DirectNamedObject out{};
    void *game_class=klass(core_image,"UnityEngine","GameObject"),*transform_class=klass(core_image,"UnityEngine","Transform");
    void *get_transform=method(game_class,"get_transform",0,0x1b87c50);
    void *get_game_object=method(klass(core_image,"UnityEngine","Component"),"get_gameObject",0,0x1b85ed0);
    void *get_child_count=method(transform_class,"get_childCount",0,0x1b98c30);
    void *get_child=method(transform_class,"GetChild",1,0x1b970d0);
    if(!typed(parent,"GameObject","UnityEngine",true)||!target||!get_transform||!get_game_object||!get_child_count||!get_child){out.reason="direct_child_metadata_guard";return out;}
    void *start=nullptr,*box=nullptr;
    if(!invoke(get_transform,parent,nullptr,start)||!derived_unity(start,"Transform","UnityEngine")){out.reason="direct_child_parent_guard";return out;}
    if(!invoke(get_child_count,start,nullptr,box)){out.reason="direct_child_count_call";return out;}
    int32_t children=0;
    if(!boxed_int(box,children)||children<0||children>512){out.reason="direct_child_count_bound";return out;}
    for(int32_t i=0;i<children;++i) {
        void *child=nullptr,*object=nullptr,*args[]={&i};
        if(!invoke(get_child,start,args,child)||!derived_unity(child,"Transform","UnityEngine")){out.reason="direct_child_transform_guard";return out;}
        if(!invoke(get_game_object,child,nullptr,object)||!typed(object,"GameObject","UnityEngine",true)){out.reason="direct_child_object_guard";return out;}
        char name[129]{};if(!object_name(object,name,sizeof(name))){out.reason="direct_child_name_guard";return out;}
        if(std::strcmp(name,target))continue;
        ++out.matches;bool active=false;
        if(!active_hierarchy(object,active)){out.reason="direct_child_active_probe_failed";return out;}
        if(active)++out.active_matches;
        if((!require_active||active)){++out.compatible_matches;if(out.compatible_matches==1)out.object=object;}
    }
    out.reason=out.compatible_matches==1?"ready":out.compatible_matches>1?"direct_child_ambiguous":
        out.matches?"direct_child_active_missing":"direct_child_name_missing";
    return out;
}
bool button_ready(void *object,void *&button,const char *&reason) {
    bool active=false;button=nullptr;
    if(!active_hierarchy(object,active)||!active){reason="button_inactive";return false;}
    button=component(object,ui_image,"UnityEngine.UI","Button");
    if(!typed(button,"Button","UnityEngine.UI",true)){reason="button_component_guard";return false;}
    void *enabled_method=method(klass(core_image,"UnityEngine","Behaviour"),"get_isActiveAndEnabled",0,0x1b85a30),*box=nullptr;
    bool enabled=false;if(!invoke(enabled_method,button,nullptr,box)||!boxed_bool(box,enabled)||!enabled){reason="button_component_inactive";return false;}
    void *m=method(klass(ui_image,"UnityEngine.UI","Selectable"),"IsInteractable",0,0x1c59ab0);
    bool interactable=false;if(!invoke(m,button,nullptr,box)||!boxed_bool(box,interactable)||!interactable){reason="button_not_interactable";return false;}
    reason="ready";return true;
}
bool invoke_button(void *object,const char *&reason) {
    void *button=nullptr;if(!button_ready(object,button,reason))return false;
    void *event=field<void*>(button,0xf8);
    if(!derived(event,"UnityEvent","UnityEngine.Events")){reason="button_event_guard";return false;}
    void *m=method(klass(core_image,"UnityEngine.Events","UnityEvent"),"Invoke",0,0x1bb0190),*ignored=nullptr;
    if(!invoke(m,event,nullptr,ignored)){reason="button_event_exception";return false;}
    reason="button_event_dispatched";return true;
}
bool select_object(void *event_system,void *object,const char *&reason) {
    bool active=false;if(!typed(event_system,"EventSystem","UnityEngine.EventSystems",true)||!active_hierarchy(object,active)||!active){reason="selection_context_guard";return false;}
    void *m=method(klass(ui_image,"UnityEngine.EventSystems","EventSystem"),"SetSelectedGameObject",1,0x1c668a0),*ignored=nullptr;
    void *args[]={object};if(!invoke(m,event_system,args,ignored)){reason="selection_callback_exception";return false;}
    reason="selection_dispatched";return true;
}
bool transform_child_count(void *transform,int32_t &count) {
    void *m=method(klass(core_image,"UnityEngine","Transform"),"get_childCount",0,0x1b98c30),*box=nullptr;
    return derived_unity(transform,"Transform","UnityEngine")&&invoke(m,transform,nullptr,box)&&boxed_int(box,count)&&count>=0&&count<=4096;
}
bool tile_text(void *root,void *text_type,const char *target,void *&match,char name[65],const char *&failure) {
    match=nullptr;name[0]=0;
    void *game_class=klass(core_image,"UnityEngine","GameObject");
    void *transform_class=klass(core_image,"UnityEngine","Transform");
    void *component_class=klass(core_image,"UnityEngine","Component");
    void *object_class=klass(core_image,"UnityEngine","Object");
    void *get_transform=method(game_class,"get_transform",0,0x1b87c50);
    void *get_component=method(game_class,"GetComponent",1,0x1b87620);
    void *get_game_object=method(component_class,"get_gameObject",0,0x1b85ed0);
    void *get_child_count=method(transform_class,"get_childCount",0,0x1b98c30);
    void *get_child=method(transform_class,"GetChild",1,0x1b970d0);
    void *get_name=method(object_class,"get_name",0,0x1b8c010);
    if(!typed(root,"GameObject","UnityEngine",true)){failure="tile_root_gameobject_guard";return false;}
    if(!text_type){failure="text_type_unavailable";return false;}
    if(!get_transform||!get_component||!get_game_object||!get_child_count||!get_child||!get_name){
        failure="tile_metadata_method_guard";return false;
    }
    void *root_transform=nullptr;
    if(!invoke(get_transform,root,nullptr,root_transform)){failure="root_transform_call_failed";return false;}
    if(!derived_unity(root_transform,"Transform","UnityEngine")){failure="root_transform_guard";return false;}
    void *stack[128]{};unsigned used=1,found=0;stack[0]=root_transform;
    while(used) {
        void *transform=stack[--used],*game_object=nullptr,*text=nullptr,*boxed=nullptr;
        if(!derived_unity(transform,"Transform","UnityEngine")){failure="traversal_transform_guard";return false;}
        if(!invoke(get_game_object,transform,nullptr,game_object)){failure="tile_gameobject_call_failed";return false;}
        if(!typed(game_object,"GameObject","UnityEngine",true)){failure="tile_gameobject_guard";return false;}
        void *component_args[]={text_type};
        if(!invoke(get_component,game_object,component_args,text)){failure="tile_component_call_failed";return false;}
        if(text) {
            if(!typed(text,"Text","UnityEngine.UI",true)){failure="tile_text_component_guard";return false;}
            char text_value[65]{},object_name[68]{};
            if(!ascii_preset(field<void*>(text,0xe0),text_value)){failure="tile_text_value_invalid";return false;}
            if(!invoke(get_name,game_object,nullptr,boxed)){failure="tile_name_call_failed";return false;}
            if(!managed_string(boxed,object_name,sizeof(object_name))){failure="tile_name_value_invalid";return false;}
            size_t length=std::strlen(text_value);
            if(std::strlen(object_name)==length+3&&!std::memcmp(object_name,"txt",3)&&
               !std::memcmp(object_name+3,text_value,length+1)) {
                if(++found>1){failure="tile_text_ambiguous";return false;}
                std::memcpy(name,text_value,length+1);
                if(target&&!std::strcmp(target,text_value))match=text;
            }
        }
        if(!invoke(get_child_count,transform,nullptr,boxed)){failure="child_count_call_failed";return false;}
        int32_t children=0;
        if(!boxed_int(boxed,children)){failure="child_count_value_invalid";return false;}
        if(children<0||children>64||used+unsigned(children)>128){failure="child_traversal_bound";return false;}
        for(int32_t i=children-1;i>=0;--i) {
            void *child=nullptr,*args[]={&i};
            if(!invoke(get_child,transform,args,child)){failure="child_transform_call_failed";return false;}
            if(!derived_unity(child,"Transform","UnityEngine")){failure="child_transform_guard";return false;}
            stack[used++]=child;
        }
    }
    if(found!=1){failure="tile_text_contract_missing";return false;}
    return true;
}
PresetTiles scan_presets(void *menu,const char *target) {
    PresetTiles out{};
    if(!typed(menu,"CE_Menu","",true)||!readable(menu,0x329)){out.scan_reason="menu_header_unavailable";return out;}
    void *text_class=klass(ui_image,"UnityEngine.UI","Text");
    if(!text_class){out.scan_reason="text_class_unavailable";return out;}
    const void *text_type_raw=text_class?api.class_type(text_class):nullptr;
    void *text_type=text_type_raw?api.type_object(text_type_raw):nullptr;
    if(!text_type){out.scan_reason="text_type_unavailable";return out;}
    int32_t count=0;void **items=nullptr;
    const char *failure=nullptr;
    if(!list_items(field<void*>(menu,0xc0),count,items,failure)){out.scan_reason=failure?failure:"list_probe_failed";return out;}
    out.count=uint32_t(count);
    for(int32_t i=0;i<count;++i) {
        void *match=nullptr;char name[65]{};
        if(!tile_text(items[i],text_type,target,match,name,failure)){
            PresetTiles failed{};failed.scan_reason=failure?failure:"tile_probe_failed";return failed;
        }
        if(out.name_count<32)std::memcpy(out.names[out.name_count++],name,sizeof(name));
        else out.names_truncated=true;
        if(match){++out.matches;if(out.matches==1)out.match=match;}
    }
    if(!game_object_active(field<void*>(menu,0x220),out.menu_active)){
        PresetTiles failed{};failed.scan_reason="menu_active_probe_failed";return failed;
    }
    if(!game_object_active(field<void*>(menu,0x258),out.loading_active)){
        PresetTiles failed{};failed.scan_reason="loading_active_probe_failed";return failed;
    }
    out.probe_ok=true;out.scan_reason="ready";return out;
}
nac::PresetState observe_preset(void *owner,void *&menu,void *&click,void *&open,PresetTiles &tiles,const char *target) {
    nac::PresetState s{};char scene[1025]{},session[1025]{};
    s.scene_editor=active_scene(scene,sizeof(scene))&&!std::strcmp(scene,"CharacterEditor");
    s.current_owner=singleton(api.object_class(owner),"_singleton")==owner;
    s.session_ready=managed_string(field<void*>(owner,0xe8),session,sizeof(session))&&session[0];
    SecureZeroMemory(session,sizeof(session));
    void *cl=klass(script_image,"","CE_Menu");menu=singleton(cl,"_singleton");
    s.alive=typed(menu,"CE_Menu","",true)&&readable(menu,0x329);
    s.initialized=s.alive&&field<uint8_t>(menu,0x328);
    s.controller_ready=s.alive&&typed(field<void*>(menu,0x98),"CHARACTEREDITOR_SLIDERS","",true);
    s.preset_manager_ready=s.alive&&typed(field<void*>(menu,0x28),"ManagerPreset");
    void *editor=singleton(klass(script_image,"","MANAGEREditor"),"_singleton");
    s.cloud_ready=typed(editor,"MANAGEREditor","",true)&&typed(field<void*>(editor,0x178),"NETGcloudEditor");
    s.event_system_ready=s.alive&&typed(field<void*>(menu,0x58),"EventSystem","UnityEngine.EventSystems",true);
    s.load_menu_ready=s.alive&&typed(field<void*>(menu,0x220),"GameObject","UnityEngine",true);
    s.loading_circle_ready=s.alive&&typed(field<void*>(menu,0x228),"GameObject","UnityEngine",true);
    s.loading_preset_ready=s.alive&&typed(field<void*>(menu,0x258),"GameObject","UnityEngine",true);
    click=method(cl,"onClickPreset",1,0x490090);open=method(cl,"onClickBTNMENU_LoadPreset",0,0x48f940);
    if(s.alive&&click&&open)tiles=scan_presets(menu,target);
    else if(s.alive)tiles.scan_reason="preset_callback_method_guard";
    if(tiles.probe_ok&&tiles.menu_active&&tiles.count>0) {
        char digest[65]{};
        if(session_digest(owner,digest)) {
            observed_names_count=tiles.name_count;observed_names_truncated=tiles.names_truncated;
            std::memset(observed_names,0,sizeof(observed_names));
            for(uint32_t i=0;i<tiles.name_count&&i<32;++i)std::memcpy(observed_names[i],tiles.names[i],65);
            std::memcpy(observed_names_digest,digest,65);observed_names_at=GetTickCount64();
        }
    }
    s.tiles_probe_ok=tiles.probe_ok;s.menu_active=tiles.menu_active;s.loading_active=tiles.loading_active;s.matches=tiles.matches;
    return s;
}
bool invoke_preset_tile(const nac::PresetState &state,void *menu,void *click,void *text,const char *target,const char *&code) {
    auto result=nac::dispatch_preset_text(state,click,menu,text,api.invoke);
    if(result==nac::PresetDispatch::Exception){code="preset_callback_exception";return false;}
    if(result!=nac::PresetDispatch::Started){code="preset_callback_guard";return false;}
    char current[65]{};
    if(!ascii_preset(field<void*>(menu,0xc8),current)||std::strcmp(current,target)) {
        code="preset_callback_did_not_accept";return false;
    }
    bool loading=false;
    if(!game_object_active(field<void*>(menu,0x258),loading)||!loading) {
        code="preset_loading_generation_not_started";return false;
    }
    code="native_preset_callback_dispatched";return true;
}
void set_preset_pending(const char *target,uint64_t deadline,uint32_t phase,const char *code) {
    std::memset(preset_target,0,sizeof(preset_target));
    std::memcpy(preset_target,target,std::strlen(target)+1);
    preset_deadline=deadline;preset_phase=phase;preset_pending=true;preset_loading_seen=false;preset_last_code=code;
}
void service_preset_pending(void *owner,uint64_t now) {
    if(!preset_pending)return;
    if(now>preset_deadline){preset_pending=false;preset_loading_seen=false;preset_phase=0;preset_last_code="preset_deadline_expired";return;}
    void *menu=nullptr,*click=nullptr,*open=nullptr;PresetTiles tiles{};
    auto state=observe_preset(owner,menu,click,open,tiles,preset_target);
    const char *reason=nac::preset_reason(state);
    if(std::strcmp(reason,"ready")) {
        if(!state.scene_editor||!state.current_owner||!state.alive) {
            preset_pending=false;preset_loading_seen=false;preset_phase=0;preset_last_code="preset_context_lost";
        }
        return;
    }
    if(preset_phase==2) {
        char current[65]{};
        if(ascii_preset(field<void*>(menu,0xc8),current)&&!std::strcmp(current,preset_target)&&
           field<uint8_t>(menu,0x2a8)&&preset_loading_seen&&!tiles.loading_active&&!tiles.menu_active&&tiles.count==0) {
            preset_pending=false;preset_phase=0;preset_last_code="preset_load_completed";
        }
        return;
    }
    auto plan=nac::preset_plan(state);
    if(plan==nac::PresetPlan::DispatchTile) {
        const char *code=nullptr;bool okay=invoke_preset_tile(state,menu,click,tiles.match,preset_target,code);
        if(okay){preset_loading_seen=true;preset_phase=2;preset_last_code="preset_callback_dispatched_waiting_for_completion";}
        else {preset_pending=false;preset_loading_seen=false;preset_phase=0;preset_last_code=code?code:"preset_callback_failed";}
    }
}
const char *load_named_preset(void *owner,const char *target,uint64_t deadline,const char *&status) {
    if(remove_pending||save_pending){status="rejected";return "editor_mutation_pending";}
    if(preset_pending){status="rejected";return !std::strcmp(target,preset_target)?"preset_load_already_pending":"different_preset_load_pending";}
    void *menu=nullptr,*click=nullptr,*open=nullptr;PresetTiles tiles{};
    auto state=observe_preset(owner,menu,click,open,tiles,target);
    const char *reason=nac::preset_reason(state);
    if(std::strcmp(reason,"ready")){status="rejected";return reason;}
    if(state.loading_active){status="rejected";return "preset_load_in_progress";}
    auto plan=nac::preset_plan(state);
    if(plan==nac::PresetPlan::DispatchTile) {
        const char *code=nullptr;
        if(!invoke_preset_tile(state,menu,click,tiles.match,target,code)){status="error";preset_last_code=code;return code;}
        set_preset_pending(target,deadline,2,"preset_callback_dispatched_waiting_for_completion");
        preset_loading_seen=true;
        status="started";return preset_last_code;
    }
    if(plan==nac::PresetPlan::OpenAndWait) {
        void *ignored=nullptr;
        if(!invoke(open,menu,nullptr,ignored)){status="error";preset_last_code="preset_menu_callback_exception";return preset_last_code;}
        PresetTiles after=scan_presets(menu,target);
        if(!after.probe_ok||!after.menu_active){status="error";preset_last_code="preset_menu_callback_did_not_accept";return preset_last_code;}
        set_preset_pending(target,deadline,1,"preset_menu_opened_waiting_for_tile");
        status="started";return preset_last_code;
    }
    if(plan==nac::PresetPlan::WaitExisting) {
        set_preset_pending(target,deadline,1,"preset_menu_waiting_for_tile");
        status="started";return preset_last_code;
    }
    status="rejected";return "preset_dispatch_guard";
}

struct MutationView {
    void *menu{},*root{},*category_transform{},*category_object{},*assets{},*remove_tile{};
    bool valid{},female{},preset_loaded{};int32_t asset_count{-1},child_count{-1};
    const char *reason="not_scanned";char current_preset[65]{};
};
MutationView observe_mutation(void *owner,bool scan_tile) {
    MutationView out{};char scene[128]{};
    if(!active_scene(scene,sizeof(scene))||std::strcmp(scene,"CharacterEditor")){out.reason="wrong_scene";return out;}
    if(singleton(api.object_class(owner),"_singleton")!=owner){out.reason="ps4info_not_current";return out;}
    out.menu=singleton(klass(script_image,"","CE_Menu"),"_singleton");
    if(!typed(out.menu,"CE_Menu","",true)||!readable(out.menu,0x329)){out.reason="editor_unavailable";return out;}
    // The CE_Menu GameObject is the common authored hierarchy root; the
    // CharacterEditor and WardrobeEditor panels are siblings beneath it.
    out.root=component_game_object(out.menu);
    if(!typed(out.root,"GameObject","UnityEngine",true)){out.reason="editor_root_unavailable";return out;}
    out.female=field<uint32_t>(out.menu,0x78)==1;out.preset_loaded=field<uint8_t>(out.menu,0x2a8)!=0;
    if(!ascii_preset(field<void*>(out.menu,0xc8),out.current_preset)){out.reason="current_preset_invalid";return out;}
    int32_t count=0;void **items=nullptr;const char *failure=nullptr;
    if(!list_items(field<void*>(out.menu,0xa8),count,items,failure)){out.reason=failure?failure:"female_cloth_list_invalid";return out;}
    uint32_t matches=0;
    for(int32_t i=0;i<count;++i){
        void *transform=items[i];if(!derived_unity(transform,"Transform","UnityEngine")){out.reason="female_cloth_transform_guard";return out;}
        char name[129]{};if(!object_name(transform,name,sizeof(name))){out.reason="female_cloth_name_guard";return out;}
        if(!std::strcmp(name,"FEMALE\\CLOTH_HEAD_HAT")){++matches;out.category_transform=transform;}
    }
    if(matches!=1){out.reason=matches?"female_hat_category_ambiguous":"female_hat_category_missing";return out;}
    out.category_object=component_game_object(out.category_transform);
    if(!out.category_object){out.reason="female_hat_category_object_guard";return out;}
    bool active=false;if(!active_hierarchy(out.category_object,active)||(scan_tile&&!active)){out.reason="female_hat_category_inactive";return out;}
    out.assets=component(out.category_object,script_image,"","AssetsLoaded");
    if(!typed(out.assets,"AssetsLoaded","",true)){out.reason="female_hat_assets_guard";return out;}
    void **asset_items=nullptr;if(!list_items(field<void*>(out.assets,0x18),out.asset_count,asset_items,failure)){out.reason=failure?failure:"female_hat_assets_list_invalid";return out;}
    if(!transform_child_count(out.category_transform,out.child_count)){out.reason="female_hat_child_count_invalid";return out;}
    if(scan_tile){
        void *content=field<void*>(out.menu,0x158);
        auto tile=find_named_direct_child(content,"Imgft6Os3EO67lO5541RN276BGQrYN67khb",true);
        auto tile_disposition=nac::direct_child_scan_disposition(tile.compatible_matches,tile.reason);
        if(tile_disposition!=nac::HierarchyScanDisposition::ready){
            out.reason=tile_disposition==nac::HierarchyScanDisposition::pending?"remove_tile_pending":
                tile.compatible_matches>1?"remove_tile_ambiguous":tile.reason;
            return out;
        }
        void *item=component(tile.object,script_image,"","CW_Item");
        if(!typed(item,"CW_Item","",true)||field<int32_t>(item,0x58)!=1||field<int32_t>(item,0x5c)!=1){out.reason="remove_tile_contract_mismatch";return out;}
        void *button=nullptr;const char *button_reason=nullptr;
        if(!button_ready(tile.object,button,button_reason)){out.reason=button_reason;return out;}
        out.remove_tile=tile.object;
    }
    out.valid=true;out.reason="ready";return out;
}
bool mutation_context(void *owner,const char digest[65],bool for_remove,const char *&reason,MutationView &view) {
    char fresh[65]{};view=observe_mutation(owner,false);
    auto desktop=current_desktop_proof();
    bool same=session_digest(owner,fresh)&&nac::same_digest(digest,fresh);
    if(for_remove){
        nac::RemoveState state{};state.scene_editor=std::strcmp(view.reason,"wrong_scene")!=0;state.current_owner=std::strcmp(view.reason,"ps4info_not_current")!=0;
        state.session_same=same;state.desktop_ok=desktop.probe_ok&&desktop.matches_session&&!desktop.receives_input;
        state.female=view.valid&&view.female;state.initialized=view.valid&&field<uint8_t>(view.menu,0x328);state.preset_loaded=view.valid&&view.preset_loaded;
        state.preset_idle=!preset_pending;state.save_idle=!save_pending;state.current_preset_exact=view.valid&&!std::strcmp(view.current_preset,"FemaleOutfitA");
        reason=nac::remove_context_reason(state);
    } else {
        nac::SaveState state{};state.scene_editor=std::strcmp(view.reason,"wrong_scene")!=0;state.current_owner=std::strcmp(view.reason,"ps4info_not_current")!=0;
        state.session_same=same;state.desktop_ok=desktop.probe_ok&&desktop.matches_session&&!desktop.receives_input;
        state.female=view.valid&&view.female;state.initialized=view.valid&&field<uint8_t>(view.menu,0x328);state.preset_loaded=view.valid&&view.preset_loaded;
        state.preset_idle=!preset_pending;state.remove_idle=!remove_pending;state.remove_completed=remove_completion_observed;
        state.cache_fresh=observed_names_at&&GetTickCount64()-observed_names_at<=120000&&nac::same_digest(observed_names_digest,fresh);
        state.cache_complete=!observed_names_truncated;reason=nac::save_context_reason(state);
    }
    if(!view.valid&&(!reason||!std::strcmp(reason,"ready")))reason=view.reason;
    return reason&&!std::strcmp(reason,"ready");
}
void fail_remove(const char *code){remove_pending=false;remove_dispatched=false;remove_phase=0;remove_last_code=code;}
void fail_save(const char *code){save_pending=false;save_seen_active=false;save_phase=0;save_last_code=code;}

const char *start_remove_female_hat(void *owner,uint64_t deadline,const char *&status) {
    if(remove_requests>=nac::kMaxRemoveRequests){status="rejected";return "remove_request_limit";}
    if(remove_pending||save_pending||preset_pending){status="rejected";return "remove_action_overlap";}
    char digest[65]{};if(!session_digest(owner,digest)){status="rejected";return "remove_session_unavailable";}
    MutationView view{};const char *reason=nullptr;
    std::memcpy(remove_session_digest,digest,65);
    if(!mutation_context(owner,remove_session_digest,true,reason,view)){std::memset(remove_session_digest,0,65);status="rejected";return reason?reason:view.reason;}
    if(view.asset_count<=0||view.child_count<=0){std::memset(remove_session_digest,0,65);status="rejected";return "hat_slot_empty";}
    void *button=field<void*>(view.menu,0xf8);char button_name[65]{};
    if(!object_name(button,button_name,sizeof(button_name))||std::strcmp(button_name,"BTNMENU_WardrobeEditor")){
        std::memset(remove_session_digest,0,65);status="rejected";return "wardrobe_button_reference_mismatch";
    }
    if(!invoke_button(button,reason)){std::memset(remove_session_digest,0,65);status="error";return reason;}
    ++remove_requests;remove_pending=true;remove_completion_observed=false;remove_dispatched=false;
    head_named_matches=head_active_matches=head_compatible_matches=0;
    hat_named_matches=hat_active_matches=hat_compatible_matches=0;
    head_scan_reason=hat_scan_reason="not_scanned";
    remove_pre_assets=view.asset_count;remove_pre_children=view.child_count;
    remove_phase=1;remove_deadline=deadline;remove_last_code="remove_wardrobe_opened";status="started";return remove_last_code;
}
void service_remove_pending(void *owner,uint64_t now) {
    if(!remove_pending)return;
    if(now>remove_deadline){fail_remove("remove_generation_timeout");return;}
    MutationView view{};const char *reason=nullptr;
    if(!mutation_context(owner,remove_session_digest,true,reason,view)){fail_remove(reason?reason:"remove_context_lost");return;}
    if(remove_phase==1){
        // BTNHeadWardrobeEditor is a sibling of WardrobeEditor under the
        // serialized CE_Menu Canvas root, not a descendant of menu+0xe0.
        auto head=find_named_direct_child(view.root,"BTNHeadWardrobeEditor",true);
        head_named_matches=head.matches;head_active_matches=head.active_matches;head_compatible_matches=head.compatible_matches;head_scan_reason=head.reason;
        auto head_disposition=nac::direct_child_scan_disposition(head.compatible_matches,head.reason);
        if(head_disposition!=nac::HierarchyScanDisposition::ready){
            if(head_disposition==nac::HierarchyScanDisposition::pending){remove_last_code="head_selector_pending";return;}
            fail_remove(head.compatible_matches>1?"head_selector_ambiguous":head.reason);return;
        }
        if(!select_object(field<void*>(view.menu,0x58),head.object,reason)){fail_remove(reason);return;}
        remove_phase=2;remove_last_code="head_selector_dispatched";return;
    }
    if(remove_phase==2){
        auto head=find_named_direct_child(view.root,"BTNHeadWardrobeEditor",true);
        head_named_matches=head.matches;head_active_matches=head.active_matches;head_compatible_matches=head.compatible_matches;head_scan_reason=head.reason;
        auto current_head_disposition=nac::direct_child_scan_disposition(head.compatible_matches,head.reason);
        if(current_head_disposition!=nac::HierarchyScanDisposition::ready){
            fail_remove(current_head_disposition==nac::HierarchyScanDisposition::pending?"head_selector_generation_lost":
                        head.compatible_matches>1?"head_selector_ambiguous":head.reason);return;
        }
        auto hat=find_named_direct_child(head.object,"BTNHat",true);
        hat_named_matches=hat.matches;hat_active_matches=hat.active_matches;hat_compatible_matches=hat.compatible_matches;hat_scan_reason=hat.reason;
        auto hat_disposition=nac::direct_child_scan_disposition(hat.compatible_matches,hat.reason);
        if(hat_disposition!=nac::HierarchyScanDisposition::ready){
            if(hat_disposition==nac::HierarchyScanDisposition::pending){remove_last_code="hat_button_pending";return;}
            fail_remove(hat.compatible_matches>1?"hat_button_ambiguous":hat.reason);return;
        }
        if(!select_object(field<void*>(view.menu,0x58),hat.object,reason)||!invoke_button(hat.object,reason)){fail_remove(reason);return;}
        remove_phase=3;remove_last_code="hat_category_dispatched";return;
    }
    if(remove_phase==3){
        view=observe_mutation(owner,true);
        if(!view.valid){remove_last_code=view.reason;return;}
        if(view.asset_count<=0||view.child_count<=0){fail_remove("hat_slot_empty_before_dispatch");return;}
        if(!invoke_button(view.remove_tile,reason)){fail_remove(reason);return;}
        remove_dispatched=true;remove_phase=4;remove_last_code="remove_callback_dispatched";return;
    }
    if(remove_phase==4&&nac::remove_generation_complete(remove_dispatched,remove_pre_assets,remove_pre_children,
                                                         view.asset_count,view.child_count,true)){
        remove_pending=false;remove_dispatched=false;remove_phase=0;remove_completion_observed=true;remove_last_code="remove_completed";
    }
}

struct SaveUi {void *component{},*input{},*input_object{},*panel{},*event_object{};bool input_active{},panel_active{},event_active{};const char *reason="not_scanned";};
SaveUi observe_save_ui(const MutationView &view) {
    SaveUi out{};auto found=find_named_direct_child(view.root,"InputFieldSavePresetName",false);
    if(found.compatible_matches!=1){out.reason=found.compatible_matches?"save_component_ambiguous":
        !std::strcmp(found.reason,"direct_child_name_missing")?"save_component_missing":found.reason;return out;}
    out.component=component(found.object,script_image,"","SavePresetName");
    if(!typed(out.component,"SavePresetName","",true)||component_game_object(out.component)!=found.object){out.reason="save_component_guard";return out;}
    out.input=field<void*>(out.component,0x28);
    if(!typed(out.input,"InputField","UnityEngine.UI",true)){out.reason="save_input_guard";return out;}
    void *saving=field<void*>(view.menu,0x240);
    if(!typed(saving,"SavingPreset","",true)){out.reason="save_panel_component_guard";return out;}
    out.input_object=component_game_object(out.input);out.panel=component_game_object(saving);
    if(out.input_object!=found.object){out.reason="save_input_owner_mismatch";return out;}
    out.event_object=component_game_object(field<void*>(out.component,0x18));
    if(!out.input_object||!out.panel||!out.event_object||!active_hierarchy(out.input_object,out.input_active)||
       !game_object_active(out.panel,out.panel_active)||!active_hierarchy(out.event_object,out.event_active)){out.reason="save_ui_active_probe_failed";return out;}
    out.reason="ready";return out;
}
struct SaveInputObservation {
    bool text_probe_ok{},read_only_probe_ok{},line_type_probe_ok{},initial_empty{},read_only{};
    int32_t initial_length{-1},line_type{-1};
    const char *reason="not_probed";
};
SaveInputObservation observe_save_input(void *input) {
    SaveInputObservation out{};
    void *input_class=klass(ui_image,"UnityEngine.UI","InputField");
    void *get_text=method(input_class,"get_text",0,0x730280);
    void *get_read_only=method(input_class,"get_readOnly",0,0x1c446c0);
    void *get_line_type=method(input_class,"get_lineType",0,0x566760);
    if(!get_text){out.reason="save_input_text_method_guard";return out;}
    void *text=nullptr;
    if(!invoke(get_text,input,nullptr,text)){out.reason="save_input_text_getter_exception";return out;}
    if(!typed(text,"String","System")||!readable(text,0x14)){
        out.reason="save_input_text_value_guard";return out;
    }
    out.initial_length=field<int32_t>(text,0x10);
    if(out.initial_length<0){out.reason="save_input_text_length_guard";return out;}
    out.text_probe_ok=true;out.initial_empty=out.initial_length==0;
    if(!get_read_only){out.reason="save_input_read_only_method_guard";return out;}
    void *box=nullptr;
    if(!invoke(get_read_only,input,nullptr,box)){out.reason="save_input_read_only_getter_exception";return out;}
    if(!boxed_bool(box,out.read_only)){out.reason="save_input_read_only_value_guard";return out;}
    out.read_only_probe_ok=true;
    if(!get_line_type){out.reason="save_input_line_type_method_guard";return out;}
    box=nullptr;
    if(!invoke(get_line_type,input,nullptr,box)){out.reason="save_input_line_type_getter_exception";return out;}
    if(!boxed_exact_return_int(box,get_line_type,out.line_type)){out.reason="save_input_line_type_value_guard";return out;}
    out.line_type_probe_ok=true;out.reason="ready";return out;
}
const char *start_save_named(void *owner,const char *target,uint64_t deadline,const char *&status) {
    if(save_requests>=nac::kMaxSaveRequests){status="rejected";return "save_request_limit";}
    if(!nac::save_name_valid(target)){status="rejected";return "save_name_rejected";}
    if(save_pending||remove_pending||preset_pending){status="rejected";return "save_action_overlap";}
    char digest[65]{};if(!session_digest(owner,digest)){status="rejected";return "save_session_unavailable";}
    std::memcpy(save_session_digest,digest,65);MutationView view{};const char *reason=nullptr;
    if(!mutation_context(owner,save_session_digest,false,reason,view)){std::memset(save_session_digest,0,65);status="rejected";return reason?reason:view.reason;}
    if(nac::duplicate_name(target,observed_names,observed_names_count,observed_names_truncated)){std::memset(save_session_digest,0,65);status="rejected";return "save_name_duplicate_or_preflight_incomplete";}
    if(!std::strcmp(view.current_preset,target)){std::memset(save_session_digest,0,65);status="rejected";return "save_name_matches_current";}
    auto ui=observe_save_ui(view);if(std::strcmp(ui.reason,"ready")||ui.panel_active||ui.input_active){std::memset(save_session_digest,0,65);status="rejected";return std::strcmp(ui.reason,"ready")?ui.reason:"save_ui_generation_active";}
    void *button=field<void*>(ui.component,0x20);char button_name[65]{};
    if(!object_name(button,button_name,sizeof(button_name))||std::strcmp(button_name,"BTNMENU_SavePreset")){
        std::memset(save_session_digest,0,65);status="rejected";return "save_button_reference_mismatch";
    }
    save_input_text_probe_ok=save_input_read_only_probe_ok=save_input_line_type_probe_ok=false;
    save_input_initial_empty=save_input_read_only=false;
    save_input_initial_length=save_input_line_type=-1;save_input_probe_reason="not_probed";
    if(!invoke_button(button,reason)){std::memset(save_session_digest,0,65);status="error";return reason;}
    std::memset(save_target,0,sizeof(save_target));std::memcpy(save_target,target,std::strlen(target)+1);
    ++save_requests;save_pending=true;save_completion_observed=false;save_seen_active=false;save_phase=1;save_deadline=deadline;
    save_last_code="save_input_opened";status="started";return save_last_code;
}
void service_save_pending(void *owner,uint64_t now) {
    if(!save_pending)return;
    if(now>save_deadline){fail_save(save_seen_active?"save_rejected_or_timeout":"save_generation_not_seen");return;}
    MutationView view{};const char *reason=nullptr;
    if(!mutation_context(owner,save_session_digest,false,reason,view)){fail_save(reason?reason:"save_context_lost");return;}
    auto ui=observe_save_ui(view);if(std::strcmp(ui.reason,"ready")){fail_save(ui.reason);return;}
    if(save_phase==1){
        if(!ui.input_active||ui.panel_active){fail_save("save_input_not_active");return;}
        auto observation=observe_save_input(ui.input);
        save_input_text_probe_ok=observation.text_probe_ok;
        save_input_read_only_probe_ok=observation.read_only_probe_ok;
        save_input_line_type_probe_ok=observation.line_type_probe_ok;
        save_input_initial_empty=observation.initial_empty;save_input_read_only=observation.read_only;
        save_input_initial_length=observation.initial_length;save_input_line_type=observation.line_type;
        save_input_probe_reason=observation.reason;
        if(std::strcmp(observation.reason,"ready")){fail_save(observation.reason);return;}
        if(!observation.initial_empty){save_input_probe_reason="save_input_initial_text_nonempty";fail_save(save_input_probe_reason);return;}
        if(observation.read_only){save_input_probe_reason="save_input_read_only";fail_save(save_input_probe_reason);return;}
        if(observation.line_type!=0){save_input_probe_reason="save_input_line_type_mismatch";fail_save(save_input_probe_reason);return;}
        std::uint16_t utf16[17]{};size_t length=std::strlen(save_target);for(size_t i=0;i<length;++i)utf16[i]=uint8_t(save_target[i]);
        void *managed=api.string_new_utf16(utf16,int32_t(length));
        void *setter=method(klass(ui_image,"UnityEngine.UI","InputField"),"set_text",1,0x1c45560);
        auto result=nac::invoke_reference(setter,ui.input,managed,api.invoke);
        if(result!=nac::ReferenceDispatch::started){fail_save(result==nac::ReferenceDispatch::exception?"save_input_setter_exception":"save_input_setter_guard");return;}
        void *get_text=method(klass(ui_image,"UnityEngine.UI","InputField"),"get_text",0,0x730280);
        void *text=nullptr;char current[65]{};
        if(!invoke(get_text,ui.input,nullptr,text)||!managed_string(text,current,sizeof(current))||std::strcmp(current,save_target)){fail_save("save_input_text_mismatch");return;}
        void *callback=method(klass(script_image,"","SavePresetName"),"OnSavePreset",0,0x671050),*ignored=nullptr;
        if(!invoke(callback,ui.component,nullptr,ignored)){fail_save("save_callback_exception");return;}
        auto after=observe_save_ui(view);
        if(!std::strcmp(after.reason,"ready")&&after.panel_active)save_seen_active=true;
        save_phase=2;save_last_code=save_seen_active?"save_generation_active":"save_callback_dispatched";return;
    }
    if(save_phase==2){
        if(ui.panel_active){save_seen_active=true;save_last_code="save_generation_active";return;}
        if(nac::save_generation_complete(true,save_seen_active,ui.panel_active,ui.input_active,ui.event_active,
                                         !std::strcmp(view.current_preset,save_target),true)){
            save_pending=false;save_phase=0;save_completion_observed=true;save_last_code="save_completed";return;
        }
    }
}
nac::WardrobeState observe_wardrobe(void *owner,void *&manager,void *&target) {
    nac::WardrobeState s{};char scene[1025]{},text[1025]{};void *identity=nullptr;
    s.scene_world=active_scene(scene,sizeof(scene))&&scene[0]&&std::strcmp(scene,"Login")&&
        std::strcmp(scene,"PreInitiLOAD")&&std::strcmp(scene,"InitLOAD")&&std::strcmp(scene,"CharacterEditor");
    s.current_owner=singleton(api.object_class(owner),"_singleton")==owner;
    s.network=observe_network(identity);s.in_space=field<uint8_t>(owner,0xfa);
    void *cl=klass(script_image,"","ManagerInstance");manager=singleton(cl,"_singleton");
    s.manager_alive=derived_unity(manager,"ManagerInstance")&&readable(manager,0x2c8);
    if(s.manager_alive) {
        s.local_player_done=field<uint8_t>(manager,0x121);s.travelling=field<uint8_t>(manager,0x122);
        s.open=field<uint8_t>(manager,0x120);
        void *memory=field<void*>(manager,0x2c0),*info=field<void*>(memory,0x10),*player=field<void*>(info,0x30);
        void *avatar=field<void*>(player,0x18),*input=field<void*>(player,0x60),*side=field<void*>(player,0x80);
        void *interactor=field<void*>(player,0x50);
        s.local_player_ready=typed(memory,"Memory","Assets.Scripts.Memories")&&
            typed(info,"PlayerInfo","Assets.Scripts.Memories")&&typed(player,"NebulaPlayer","",true)&&
            field<uint8_t>(player,0x9c)&&field<void*>(player,0xf8)==identity&&s.network.local_player_alive&&
            typed(avatar,"NebulaPlayerAvatar","Assets.Scripts.NebulaPlayers",true)&&field<uint32_t>(avatar,0x104)<=1&&
            typed(side,"NebulaInputSideMenu","Assets.Scripts.NebulaPlayers",true)&&
            typed(input,"NebulaInput","Assets.Scripts.NebulaPlayers",true)&&
            typed(interactor,"NebulaInteractor","Assets.Scripts.NebulaPlayers",true)&&
            typed(field<void*>(manager,0x1e0),"GameObject","UnityEngine",true)&&
            managed_string(field<void*>(owner,0xe0),text,sizeof(text))&&
            managed_string(field<void*>(owner,0xe8),text,sizeof(text))&&text[0]&&
            managed_string(field<void*>(player,0xc0),text,sizeof(text))&&
            managed_string(field<void*>(player,0xc8),text,sizeof(text));
        SecureZeroMemory(text,sizeof(text));
        void *chat=field<void*>(manager,0x150),*notifications=field<void*>(chat,0x28);
        s.notifications_ready=typed(chat,"Chat","",true)&&typed(notifications,"NotificationsManager","",true)&&
            readable(field<void*>(notifications,0xc0),0x20)&&readable(field<void*>(notifications,0xc8),0x20);
        s.tcp_ready=typed(field<void*>(manager,0x2b8),"TCPClient","TCPs");
    }
    s.pad_ready=typed(singleton(klass(script_image,"","PadPS4"),"padPS4"),"PadPS4");
    void *loader=singleton(klass(script_image,"","ScreenLoader"),"instance");
    s.loader_ready=typed(loader,"ScreenLoader","",true)&&typed(field<void*>(loader,0x20),"SpinCircle","",true);
    target=method(cl,"OpenCharacterEditor",0,0x439800);s.method_ready=target;return s;
}
const char *open_wardrobe(void *owner,const char *&status) {
    // Reacquire every object and MethodInfo on this frame; retain no Unity pointer.
    void *manager=nullptr,*target=nullptr;auto state=observe_wardrobe(owner,manager,target);
    const char *reason=nac::wardrobe_reason(state);
    if(std::strcmp(reason,"ready")){status="rejected";return reason;}
    auto result=nac::dispatch_wardrobe(state,target,manager,api.invoke);
    if(result==nac::WardrobeResult::Exception){status="error";return "wardrobe_callback_exception";}
    if(result!=nac::WardrobeResult::Started){status="rejected";return "wardrobe_dispatch_guard";}
    // This flag is set by the original callback before HTTP. Never write/clear it.
    if(!derived_unity(manager,"ManagerInstance")||!field<uint8_t>(manager,0x120)) {
        status="error";return "wardrobe_callback_did_not_accept";
    }
    status="started";return "native_wardrobe_callback_dispatched";
}
nebula_frame_capture::Api frame_capture_api() {
    nebula_frame_capture::Api out{};
    out.game_base=reinterpret_cast<std::uintptr_t>(game);
    out.readable=readable;
    out.domain_get=api.domain_get;
    out.domain_get_assemblies=api.assemblies;
    out.assembly_get_image=api.assembly_image;
    out.image_get_name=api.image_name;
    out.class_from_name=api.class_from_name;
    out.class_get_method_from_name=api.class_method;
    out.string_new_utf16=api.string_new_utf16;
    out.runtime_invoke=api.invoke;
    return out;
}
const char *capture_frame(uint32_t sequence,const char *&status) {
    static_assert(sizeof(wchar_t)==sizeof(std::uint16_t),"Windows UTF-16 wchar_t required");
    const auto desktop=current_desktop_proof();
    const auto *trusted=reinterpret_cast<const std::uint16_t*>(directory);
    const std::size_t length=std::wcslen(directory);

    // Derive the exact fixed output solely from the trusted session and NAC1
    // sequence so the absence check addresses the same path passed to Unity.
    nebula_frame_capture::FramePath expected{};
    const auto path_status=nebula_frame_capture::build_frame_path(
        trusted,length,sequence,frame_capture_state.capture.last_started_sequence,true,expected);
    bool output_absent=true;
    if(path_status==nebula_frame_capture::PathStatus::ok) {
        SetLastError(ERROR_SUCCESS);
        DWORD attributes=GetFileAttributesW(reinterpret_cast<const wchar_t*>(expected.value));
        output_absent=attributes==INVALID_FILE_ATTRIBUTES&&GetLastError()==ERROR_FILE_NOT_FOUND;
    }
    const auto result=nac::dispatch_frame_capture(
        frame_capture_state,desktop,frame_capture_api(),trusted,length,sequence,output_absent);
    if(result.dispatch==nac::FrameCaptureDispatch::request_limit) {
        status="rejected";return "frame_capture_request_limit";
    }
    if(result.dispatch==nac::FrameCaptureDispatch::desktop_guard) {
        status="rejected";return "frame_capture_desktop_guard";
    }
    if(result.dispatch==nac::FrameCaptureDispatch::started) {
        status="started";return "unity_frame_capture_started";
    }
    const auto failure=result.capture.result;
    status=(failure==nebula_frame_capture::Result::invalid_directory||
            failure==nebula_frame_capture::Result::invalid_sequence||
            failure==nebula_frame_capture::Result::sequence_not_increasing||
            failure==nebula_frame_capture::Result::output_exists||
            failure==nebula_frame_capture::Result::path_too_long)?"rejected":"error";
    return nebula_frame_capture::result_name(failure);
}

#include "v16_shared_core.inc"
bool store_phase_pending(){return economy_pending();}
#include "extension_hooks.inc"
#include "v16_social_core.inc"
#include "social_owned_identity_diagnostic.inc"
#include "public_chat_core.inc"
#include "row_matcher_diagnostic.inc"
#include "resource_player_info_netid.inc"
#include "resource_ui_core.inc"
#include "resource_navigation_core.inc"
#include "housing_native.inc"
#include "settings_native_core.inc"
#include "settings_open_core.inc"
#include "settings_sidebar_core.inc"
#include "settings_open_diagnostic.inc"
#include "peer_pose_core.inc"
#include "housing_wiring.inc"
#include "character_exit_core.inc"
void add_join_queue_snapshot(Json& j) {
    nebula_join_gate::Statistics s{};nebula_join_gate::statistics(s);
    j.append(",\"join_queue_gate\":{\"calls\":");j.integer(s.calls);
    j.append(",\"permits\":");j.integer(s.permits);
    j.append(",\"holds\":");j.integer(s.holds);
    j.append(",\"rejections\":");j.integer(s.rejections);
    j.append(",\"closed\":");j.integer(s.closed);
    j.append(",\"reason\":");j.integer(s.reason);j.append("}");
}
void add_snapshot(Json &j,void *owner) {
    char value[1025]{},hash[65]{};
    j.append(",\"snapshot\":{\"thread_id\":");j.integer(thread);
    j.append(",\"pid\":");j.integer(GetCurrentProcessId());j.append(",\"pump_count\":");j.integer(pumps);
    auto desktop=current_desktop_proof();
    j.append(",\"desktop\":{\"probe_ok\":");j.boolean(desktop.probe_ok);
    j.append(",\"matches_session\":");j.boolean(desktop.matches_session);
    j.append(",\"receives_input\":");j.boolean(desktop.receives_input);j.append("}");
    j.append(",\"background_requested\":");j.boolean(background_requested);
    j.append(",\"account_sha256\":");if(account_hash(owner,hash))j.string(hash);else j.append("null");
    j.append(",\"loading\":");j.boolean(field<uint8_t>(owner,0x95));
    j.append(",\"connected\":");j.boolean(field<uint8_t>(owner,0x9a));
    j.append(",\"in_space\":");j.boolean(field<uint8_t>(owner,0xfa));
    j.append(",\"gender\":");if(managed_string(field<void*>(owner,0x108),value,sizeof(value)))j.string(value);else j.append("null");
    j.append(",\"scene\":");
    if(active_scene(value,sizeof(value)))j.string(value);else j.append("null");
    void *login=nullptr,*target=nullptr;auto login_state=observe_login(owner,login,target);
    j.append(",\"login\":{\"alive\":");j.boolean(login_state.alive);
    j.append(",\"session_ready\":");j.boolean(login_state.session_ready);
    j.append(",\"pressed\":");j.boolean(login_state.pressed);
    j.append(",\"steam_ready\":");j.boolean(login_state.steam_ready);
    j.append(",\"loader_ready\":");j.boolean(login_state.loader_ready);
    j.append(",\"invoked\":");j.boolean(login_state.invoked);
    j.append(",\"reason\":");j.string(nac::login_reason(login_state));
    j.append(",\"ready\":");j.boolean(!std::strcmp(nac::login_reason(login_state),"ready"));j.append("}");
    void *local_identity=nullptr;auto network=observe_network(local_identity);
    j.append(",\"network\":{\"probe_ok\":");j.boolean(network.probe_ok);
    j.append(",\"connected\":");j.boolean(network.connected);j.append(",\"ready\":");j.boolean(network.ready);
    j.append(",\"local_player_alive\":");j.boolean(network.local_player_alive);
    j.append(",\"authenticated\":");j.boolean(network.authenticated);
    j.append(",\"connection_ready\":");j.boolean(network.connection_ready);j.append("}");
    void *wardrobe_manager=nullptr,*wardrobe_target=nullptr;auto wardrobe=observe_wardrobe(owner,wardrobe_manager,wardrobe_target);
    const char *wardrobe_reason=nac::wardrobe_reason(wardrobe);
    j.append(",\"wardrobe\":{\"ready\":");j.boolean(!std::strcmp(wardrobe_reason,"ready"));
    j.append(",\"reason\":");j.string(wardrobe_reason);j.append("}");
    void *manager=singleton(klass(script_image,"","ManagerInstance"),"_singleton");
    bool manager_alive=derived_unity(manager,"ManagerInstance")&&readable(manager,0x123);
    j.append(",\"manager\":{\"alive\":");j.boolean(manager_alive);
    bool done=manager_alive&&field<uint8_t>(manager,0x121),travelling=manager_alive&&field<uint8_t>(manager,0x122);
    j.append(",\"local_player_done\":");j.boolean(done);j.append(",\"travelling\":");j.boolean(travelling);
    j.append(",\"wardrobe_open\":");j.boolean(manager_alive&&field<uint8_t>(manager,0x120));
    j.append(",\"ready\":");j.boolean(manager_alive&&done&&!travelling&&!std::strcmp(nac::network_reason(network),"ready")&&field<uint8_t>(owner,0xfa));j.append("}");
    void *menu=singleton(klass(script_image,"","CE_Menu"),"_singleton");
    bool alive=typed(menu,"CE_Menu","",true);
    j.append(",\"editor\":{\"alive\":");j.boolean(alive);
    if(alive) {
        j.append(",\"gender_index\":");j.integer(field<uint32_t>(menu,0x78));
        j.append(",\"initialized\":");j.boolean(field<uint8_t>(menu,0x328));
        j.append(",\"preset_loaded\":");j.boolean(field<uint8_t>(menu,0x2a8));
        j.append(",\"current_preset\":");if(managed_string(field<void*>(menu,0xc8),value,sizeof(value)))j.string(value);else j.append("null");
        j.append(",\"controller_alive\":");j.boolean(typed(field<void*>(menu,0x98),"CHARACTEREDITOR_SLIDERS","",true));
        void *list=field<void*>(menu,0xc0);
        j.append(",\"preset_tile_count\":");if(readable(list,0x20)){int32_t n=field<int32_t>(list,0x18);if(n>=0&&n<=256)j.integer(unsigned(n));else j.append("null");}else j.append("null");
    }
    void *preset_menu=nullptr,*preset_click=nullptr,*preset_open=nullptr;PresetTiles preset_tiles{};
    auto preset_state=observe_preset(owner,preset_menu,preset_click,preset_open,preset_tiles,nullptr);
    j.append(",\"preset_probe_ok\":");j.boolean(preset_tiles.probe_ok);
    j.append(",\"preset_menu_active\":");j.boolean(preset_tiles.menu_active);
    j.append(",\"preset_loading_active\":");j.boolean(preset_tiles.loading_active);
    j.append(",\"preset_names\":[");
    for(uint32_t i=0;i<preset_tiles.name_count;++i){if(i)j.append(",");j.string(preset_tiles.names[i]);}
    j.append("],\"preset_names_truncated\":");j.boolean(preset_tiles.names_truncated);
    j.append(",\"preset_pending\":");j.boolean(preset_pending);
    j.append(",\"preset_phase\":");j.integer(preset_phase);
    j.append(",\"preset_loading_seen\":");j.boolean(preset_loading_seen);
    j.append(",\"preset_target\":");if(preset_target[0])j.string(preset_target);else j.append("null");
    j.append(",\"preset_status\":");j.string(preset_last_code);
    j.append(",\"preset_completion_observed\":");j.boolean(!preset_pending&&!std::strcmp(preset_last_code,"preset_load_completed"));
    j.append(",\"preset_reason\":");j.string(nac::preset_reason(preset_state));
    j.append(",\"preset_scan_reason\":");j.string(preset_tiles.scan_reason);
    j.append(",\"preset_ready\":");j.boolean(!std::strcmp(nac::preset_reason(preset_state),"ready"));
    char mutation_digest[65]{};MutationView mutation=observe_mutation(owner,false);
    j.append(",\"session_digest\":");if(session_digest(owner,mutation_digest))j.string(mutation_digest);else j.append("null");
    j.append(",\"remove_pending\":");j.boolean(remove_pending);
    j.append(",\"remove_target\":\"female_hat\"");
    j.append(",\"remove_status\":");j.string(remove_last_code);
    j.append(",\"remove_reason\":");j.string(mutation.reason);
    j.append(",\"head_named_matches\":");j.integer(head_named_matches);
    j.append(",\"head_active_matches\":");j.integer(head_active_matches);
    j.append(",\"head_compatible_matches\":");j.integer(head_compatible_matches);
    j.append(",\"head_scan_reason\":");j.string(head_scan_reason);
    j.append(",\"head_ancestor_contract\":\"ce_menu_canvas_direct\"");
    j.append(",\"head_scan_scope\":\"ce_menu_canvas_direct_children\"");
    j.append(",\"hat_named_matches\":");j.integer(hat_named_matches);
    j.append(",\"hat_active_matches\":");j.integer(hat_active_matches);
    j.append(",\"hat_compatible_matches\":");j.integer(hat_compatible_matches);
    j.append(",\"hat_scan_reason\":");j.string(hat_scan_reason);
    j.append(",\"hat_ancestor_contract\":\"head_selector_direct\"");
    j.append(",\"hat_scan_scope\":\"head_selector_direct_children\"");
    j.append(",\"remove_completion_observed\":");j.boolean(remove_completion_observed);
    j.append(",\"hat_asset_count\":");if(mutation.valid)j.integer(unsigned(mutation.asset_count));else j.append("null");
    j.append(",\"hat_child_count\":");if(mutation.valid)j.integer(unsigned(mutation.child_count));else j.append("null");
    j.append(",\"hat_equipped_state\":");
    if(!mutation.valid)j.string("unknown");else if(!mutation.asset_count&&!mutation.child_count)j.string("empty");
    else if(mutation.asset_count>0&&mutation.child_count>0&&!std::strcmp(mutation.current_preset,"FemaleOutfitA"))j.string("expected");else j.string("other");
    j.append(",\"save_pending\":");j.boolean(save_pending);
    j.append(",\"save_target\":");if(save_target[0])j.string(save_target);else j.append("null");
    j.append(",\"save_status\":");j.string(save_last_code);
    j.append(",\"save_seen_active\":");j.boolean(save_seen_active);
    j.append(",\"save_completion_observed\":");j.boolean(save_completion_observed);
    j.append(",\"save_input_probe_reason\":");j.string(save_input_probe_reason);
    j.append(",\"save_input_text_probe_ok\":");j.boolean(save_input_text_probe_ok);
    j.append(",\"save_input_initial_length\":");if(save_input_initial_length>=0)j.integer(unsigned(save_input_initial_length));else j.append("null");
    j.append(",\"save_input_initial_empty\":");j.boolean(save_input_initial_empty);
    j.append(",\"save_input_read_only_probe_ok\":");j.boolean(save_input_read_only_probe_ok);
    j.append(",\"save_input_read_only\":");j.boolean(save_input_read_only);
    j.append(",\"save_input_line_type_probe_ok\":");j.boolean(save_input_line_type_probe_ok);
    j.append(",\"save_input_line_type\":");if(save_input_line_type>=0)j.integer(unsigned(save_input_line_type));else j.append("null");
    auto save_ui=mutation.valid?observe_save_ui(mutation):SaveUi{};
    j.append(",\"save_reason\":");j.string(save_ui.reason);
    j.append(",\"save_panel_active\":");j.boolean(save_ui.panel_active);
    j.append(",\"save_input_active\":");j.boolean(save_ui.input_active);
#include "v16_snapshot.inc"
    j.append("}");add_additional_snapshots(j);
    j.append(",\"frame_capture\":{\"requests\":");j.integer(frame_capture_state.requests);
    j.append(",\"max_requests\":");j.integer(nac::kMaxFrameCaptures);
    j.append(",\"last_started_sequence\":");j.integer(frame_capture_state.capture.last_started_sequence);
    j.append(",\"completion_claimed\":false}}");
}
bool publish(const nac::Command &cmd,const char *status,const char *code,void *owner) {
    Json j;j.append("{\"format_version\":1,\"nonce\":");j.string(nonce);j.append(",\"sequence\":");j.integer(cmd.sequence);
    j.append(",\"action\":");j.string(nac::action_name(cmd.action));j.append(",\"status\":");j.string(status);
    j.append(",\"code\":");j.string(code);j.append(",\"monotonic_ms\":");j.integer(GetTickCount64());add_snapshot(j,owner);add_social_snapshot(j,owner);nebula_social_owned_identity_diagnostic_v2::snapshot(j,owner);nebula_public_chat_v2::snapshot(j,owner);nebula_row_matchers_v1::snapshot(j,owner);nebula_settings_v1::snapshot(j,owner);nebula_settings_open_diagnostic_v2::snapshot(j,owner);add_housing_snapshot(j,owner);resource_ui_core::snapshot(j,owner);resource_navigation_core::snapshot(j);movement_disk_profile();movement_json(j);peer_pose::json(j,owner);character_exit::json(j);add_join_queue_snapshot(j);j.append("}\n");
    if(!j.valid||output_bytes+j.size>8*1024*1024) return false;
    wchar_t tmpname[64]{},name[64]{},tmp[kMaxPath]{},path[kMaxPath]{};
    swprintf(tmpname,64,L"result-%u.pending",cmd.sequence);swprintf(name,64,L"result-%u.json",cmd.sequence);
    if(!path_for(tmp,tmpname)||!path_for(path,name)) return false;
    HANDLE file=CreateFileW(tmp,GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL|FILE_FLAG_WRITE_THROUGH,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    DWORD written=0;bool okay=WriteFile(file,j.data,DWORD(j.size),&written,nullptr)&&written==j.size&&FlushFileBuffers(file);
    CloseHandle(file);
    if(!okay||!MoveFileExW(tmp,path,MOVEFILE_WRITE_THROUGH))return false;
    output_bytes+=j.size;return true;
}

}


extern "C" __declspec(dllexport) void NebulaAutomation_EconomyShopInfoCompleted(void *response) noexcept {
    if(valid_shop_info_generation(response))economy_callback_generation::advance_shop_info();
}
extern "C" __declspec(dllexport) void NebulaAutomation_EconomyPurchasesCompleted(void *response) noexcept {
    if(valid_purchases_generation(response))economy_callback_generation::advance_purchases();
}

extern "C" __declspec(dllexport) void NebulaAutomation_Pump(void *owner) noexcept {
    // This function is called exclusively after the original PS4Info.Update.
    // No C++ exceptions/allocating containers are used; managed actions pass
    // through runtime_invoke's explicit exception-out boundary.
    if(disabled)return;
    if(!initialized&&!initialize(owner)){disabled=true;return;}
    if(GetCurrentThreadId()!=thread||!typed(owner,"PS4Info","",true)){disabled=true;return;}
    ++pumps;uint64_t now=GetTickCount64();
    if(now-started>1800000||previous>=256||input_bytes>=128*1024||output_bytes>=8*1024*1024){disabled=true;return;}
    bool poll_due=now-last_poll>=50;
    if(poll_due){
    last_poll=now;
    service_preset_pending(owner,now);
    service_remove_pending(owner,now);
    service_save_pending(owner,now);
    character_exit::pump(owner,now);
    service_economy(owner,now);
    service_social(owner,now);
    nebula_public_chat_v2::service(owner,now);
    service_housing(owner,now);
    resource_ui_core::pump(owner,now);
    resource_navigation_core::pump(owner,now);
    service_additional_modules(owner,now);
    }
    movement_shared_pending_mask=(character_exit::pending()?128u:0u)|(economy_pending()?1u:0u)|(social_pending()?2u:0u)|(housing_pending()?4u:0u)|(resource_ui_core::pending()?8u:0u)|(additional_module_pending()?16u:0u)|(resource_navigation_core::pending()?64u:0u)|((preset_pending||remove_pending||save_pending||store_phase_pending())?32u:0u);
    movement_service();
    if(!poll_due)return;
    wchar_t path[kMaxPath]{};if(!path_for(path,L"command.txt")){disabled=true;return;}
    HANDLE file=CreateFileW(path,GENERIC_READ|DELETE,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
    if(file==INVALID_HANDLE_VALUE)return;
    BY_HANDLE_FILE_INFORMATION info{};LARGE_INTEGER size{};char raw[2049]{};DWORD got=0;
    bool okay=GetFileInformationByHandle(file,&info)&&!(info.dwFileAttributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT))&&
        GetFileSizeEx(file,&size)&&size.QuadPart>0&&size.QuadPart<=2048&&
        ReadFile(file,raw,2049,&got,nullptr)&&got==size.QuadPart;
    if(!okay||!nac::input_fits(input_bytes,got)){CloseHandle(file);disabled=true;return;}
    input_bytes+=got;
    nac::Command cmd{};
    if(!nac::parse(raw,got,nonce,now,previous,cmd)){CloseHandle(file);disabled=true;return;}
    wchar_t claimed_name[64]{},claimed[kMaxPath]{};swprintf(claimed_name,64,L"claimed-%u.txt",cmd.sequence);
    if(!path_for(claimed,claimed_name)||!nac::rename_open_input(file,claimed)){CloseHandle(file);disabled=true;return;}
    CloseHandle(file);
    previous=cmd.sequence;
    const char *status="ok",*code="snapshot";
    bool legacy_action_pending=character_exit::pending()||preset_pending||remove_pending||save_pending||store_phase_pending();
    if(movement_pending()&&cmd.action!=nac::Query){status="rejected";code="movement_action_overlap";}
    else if(legacy_action_pending&&cmd.action!=nac::Query){status="rejected";code="legacy_action_overlap";}
    else if((economy_pending()||social_pending()||nebula_public_chat_v2::pending()||housing_pending()||resource_ui_core::pending()||resource_navigation_core::pending()||additional_module_pending())&&cmd.action!=nac::Query){status="rejected";code="module_action_overlap";}
    else if(cmd.action==nac::Housing&&(preset_pending||remove_pending||save_pending)){status="rejected";code="housing_editor_overlap";}
    else if(cmd.action==nac::Housing){code=dispatch_housing(owner,cmd.argument,now,cmd.deadline,status);}
    else if(cmd.action==nac::MovementForward||cmd.action==nac::MovementReverse){code=movement_start(cmd,status);}
    else if(cmd.action==nac::BackgroundOn){if(set_background())code="run_in_background_requested";else{status="error";code="background_method_exception_or_guard";}}
    else if(cmd.action==nac::LoginStart){code=start_login(owner,status);}
    else if(cmd.action==nac::WardrobeOpen){code=open_wardrobe(owner,status);}
    else if(cmd.action==nac::LoadNamed){code=load_named_preset(owner,cmd.argument,cmd.deadline,status);}
    else if(cmd.action==nac::FrameCapture){code=capture_frame(cmd.sequence,status);}
    else if(cmd.action==nac::RemoveFemaleHat){code=start_remove_female_hat(owner,cmd.deadline,status);}
    else if(cmd.action==nac::SaveNamed){code=start_save_named(owner,cmd.argument,cmd.deadline,status);}
    else if(cmd.action==nac::CharacterExitSaved){code=character_exit::start(owner,cmd.deadline,status);}
    else if(cmd.action==nac::ShopOpenClothing||cmd.action==nac::EconomyOpen){code=dispatch_economy(owner,nebula_economy::Action::Open,now,status);}
    else if(cmd.action==nac::ShopSelectTestFemaleTorso||cmd.action==nac::EconomySelectWardrobe){code=dispatch_economy(owner,nebula_economy::Action::SelectWardrobe,now,status);}
    else if(cmd.action==nac::EconomySelectCompanion){code=dispatch_economy(owner,nebula_economy::Action::SelectCompanion,now,status);}
    else if(cmd.action==nac::EconomySelectLocomotion){code=dispatch_economy(owner,nebula_economy::Action::SelectLocomotion,now,status);}
    else if(cmd.action==nac::ShopBuySelectedLocalCrystals||cmd.action==nac::EconomyBuyCrystals){code=dispatch_economy(owner,nebula_economy::Action::BuyCrystals,now,status);}
    else if(cmd.action==nac::EconomyBuyNP){code=dispatch_economy(owner,nebula_economy::Action::BuyNP,now,status);}
    else if(cmd.action==nac::SocialFriendRequest){code=dispatch_social(owner,ns::Action::FriendRequest,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialFriendAccept){code=dispatch_social(owner,ns::Action::FriendAccept,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialFavoriteOn){code=dispatch_social(owner,ns::Action::FavoriteOn,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialFavoriteOff){code=dispatch_social(owner,ns::Action::FavoriteOff,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialBlockOn){code=dispatch_social(owner,ns::Action::BlockOn,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialBlockOff){code=dispatch_social(owner,ns::Action::BlockOff,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialSilenceOn){code=dispatch_social(owner,ns::Action::SilenceOn,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialSilenceOff){code=dispatch_social(owner,ns::Action::SilenceOff,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialInvite){code=dispatch_social(owner,ns::Action::Invite,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialInviteAccept){code=dispatch_social(owner,ns::Action::InviteAccept,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialTalk){code=dispatch_social(owner,ns::Action::Talk,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialChatSend){code=dispatch_social(owner,ns::Action::ChatSend,now,cmd.deadline,status);}
    else if(cmd.action==nac::SocialOpen){code=dispatch_social_navigation(SocialNavigate::Open,status);}
    else if(cmd.action==nac::SocialShowFriends){code=dispatch_social_navigation(SocialNavigate::Friends,status);}
    else if(cmd.action==nac::SocialShowSpaceUsers){code=dispatch_social_navigation(SocialNavigate::SpaceUsers,status);}
    else if(cmd.action==nac::SocialShowSilenced){code=dispatch_social_navigation(SocialNavigate::Silenced,status);}
    else if(cmd.action==nac::SocialShowBlocked){code=dispatch_social_navigation(SocialNavigate::Blocked,status);}
    else if(cmd.action==nac::SocialSelectPeer){code=dispatch_social_navigation(SocialNavigate::SelectPeer,status);}
    else if(cmd.action==nac::SocialShowNotifications){code=dispatch_social_notifications(owner,now,cmd.deadline,status);}
    else if(cmd.action==nac::PublicChatShow){code=nebula_public_chat_v2::show(owner,now,cmd.deadline,status);}
    else if(cmd.action==nac::PublicChatSend){code=nebula_public_chat_v2::send(owner,status);}
    else if(cmd.action==nac::SettingsToggleNotification){code=nebula_settings_v1::toggle(owner,nebula_settings_v1::Target::NotificationLoginFriend,status);}
    else if(cmd.action==nac::SettingsTogglePlatform){code=nebula_settings_v1::toggle(owner,nebula_settings_v1::Target::PlatformOnly,status);}
    else if(cmd.action==nac::SettingsOpen){code=nebula_settings_sidebar_v1::open(owner,status);}
    else if(cmd.action==nac::ResourceCompanionSelect){code=resource_ui_core::dispatch(owner,nebula_resource_ui::Action::SelectCompanion,now,cmd.deadline,status);}
    else if(cmd.action==nac::ResourceCompanionRemove){code=resource_ui_core::dispatch(owner,nebula_resource_ui::Action::RemoveCompanion,now,cmd.deadline,status);}
    else if(cmd.action==nac::ResourceLocomotionSelect){code=resource_ui_core::dispatch(owner,nebula_resource_ui::Action::SelectLocomotion,now,cmd.deadline,status);}
    else if(cmd.action==nac::ResourceLocomotionRemove){code=resource_ui_core::dispatch(owner,nebula_resource_ui::Action::RemoveLocomotion,now,cmd.deadline,status);}
    else if(cmd.action==nac::ResourceCompanionPrepareSelect){code=resource_navigation_core::dispatch(owner,nebula_resource_navigation::Action::PrepareCompanionSelect,now,cmd.deadline,status);}
    else if(cmd.action==nac::ResourceCompanionPrepareRemove){code=resource_navigation_core::dispatch(owner,nebula_resource_navigation::Action::PrepareCompanionRemove,now,cmd.deadline,status);}
    else if(cmd.action==nac::ResourceLocomotionPrepareSelect){code=resource_navigation_core::dispatch(owner,nebula_resource_navigation::Action::PrepareLocomotionSelect,now,cmd.deadline,status);}
    else if(cmd.action==nac::ResourceLocomotionPrepareRemove){code=resource_navigation_core::dispatch(owner,nebula_resource_navigation::Action::PrepareLocomotionRemove,now,cmd.deadline,status);}
    /* INTEGRATION_DISPATCH_EXTENSIONS */
    if(!publish(cmd,status,code,owner))disabled=true;
}

extern "C" __declspec(dllexport) std::uint32_t NebulaAutomation_MovementAxis(
    std::uintptr_t control,std::uintptr_t pad,std::uint32_t site,std::uint32_t original_bits) noexcept {
    if(!initialized||disabled||GetCurrentThreadId()!=thread||!movement_profile_ok)return original_bits;
    auto phase=native_movement.phase();
    if(phase!=nebula_movement::Phase::armed&&phase!=nebula_movement::Phase::moving&&phase!=nebula_movement::Phase::waiting_idle)return original_bits;
    nebula_movement::Snapshot snapshot{};
    if(!movement_snapshot(snapshot,true,site)){native_movement.cancel();return original_bits;}
    auto result=native_movement.axis(snapshot,control,pad,site,original_bits);
    if(site<2)std::memcpy(&movement_axes[site],&result,sizeof(result));
    return result;
}

BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID) {
    if(reason==DLL_PROCESS_ATTACH)DisableThreadLibraryCalls(instance);
    return TRUE;
}
