// Actual consumer source with local IL2CPP/sidecar function-table fixtures.
// No game or sidecar DLL is loaded and no listener or connection is created.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wincrypt.h>
#include <cstdint>
#include <cstring>
#include <cwchar>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace fixture {
std::wstring local;
bool api=true,profile=true,owned=true;
unsigned gets{},loads{},waits{};
void* wanted_info=reinterpret_cast<void*>(0x1234);
void* request=reinterpret_cast<void*>(0x4567);
void* original(void* url,const void* info) {
    if(!url||info!=wanted_info)std::abort();
    ++gets;return request;
}
HMODULE module_handle() {
    auto fn=&original;std::uintptr_t address{};
    static_assert(sizeof address==sizeof fn);std::memcpy(&address,&fn,sizeof fn);
    return reinterpret_cast<HMODULE>(address-0x1d9b350);
}
void* domain(){return reinterpret_cast<void*>(1);}
void** assemblies(void*,std::size_t* count){static void* values[]{reinterpret_cast<void*>(2)};*count=1;return values;}
void* image(void*){return reinterpret_cast<void*>(3);}
const char* image_name(void*){return "UnityEngine.UnityWebRequestModule.dll";}
void* klass(void*,const char* space,const char* name){return !std::strcmp(space,"UnityEngine.Networking")&&!std::strcmp(name,"UnityWebRequest")?reinterpret_cast<void*>(4):nullptr;}
const void* method(void*,const char* name,int argc){
    static void* pointer{};auto fn=&original;std::memcpy(&pointer,&fn,sizeof fn);
    return !std::strcmp(name,"Get")&&argc==1?&pointer:nullptr;
}
template<class T>FARPROC raw(T fn){FARPROC result{};static_assert(sizeof fn==sizeof result);std::memcpy(&result,&fn,sizeof fn);return result;}
HMODULE WINAPI get_module(LPCWSTR name){return api&&!std::wcscmp(name,L"GameAssembly.dll")?module_handle():nullptr;}
FARPROC WINAPI get_proc(HMODULE module,LPCSTR name){
    if(module!=module_handle())return nullptr;
    if(!std::strcmp(name,"il2cpp_domain_get"))return raw(&domain);
    if(!std::strcmp(name,"il2cpp_domain_get_assemblies"))return raw(&assemblies);
    if(!std::strcmp(name,"il2cpp_assembly_get_image"))return raw(&image);
    if(!std::strcmp(name,"il2cpp_image_get_name"))return raw(&image_name);
    if(!std::strcmp(name,"il2cpp_class_from_name"))return raw(&klass);
    if(!std::strcmp(name,"il2cpp_class_get_method_from_name"))return raw(&method);
    // Exact shipped metadata capability: no header/redirect managed methods.
    return nullptr;
}
DWORD WINAPI environment(LPCWSTR name,LPWSTR output,DWORD capacity){
    if(std::wcscmp(name,L"LOCALAPPDATA"))return GetEnvironmentVariableW(name,output,capacity);
    if(local.size()+1>capacity)return static_cast<DWORD>(local.size()+1);
    std::memcpy(output,local.c_str(),(local.size()+1)*sizeof(wchar_t));return static_cast<DWORD>(local.size());
}
}

#define GetModuleHandleW fixture::get_module
#define GetProcAddress fixture::get_proc
#define GetEnvironmentVariableW fixture::environment
#ifndef NPA_CONSUMER_SOURCE
#define NPA_CONSUMER_SOURCE "NebulaPublicAccess.cpp"
#endif
#include NPA_CONSUMER_SOURCE
#undef GetModuleHandleW
#undef GetProcAddress
#undef GetEnvironmentVariableW

bool NebulaRemote_LoadProfile(const std::wstring& origin){++fixture::loads;return fixture::profile&&origin==L"https://preservation.invalid:8443";}
bool NebulaRemote_IsLoopbackRequest(const std::wstring& url){
    static const std::wstring origin=L"http://127.0.0.1:38080";
    return url==origin||(url.size()>origin.size()&&url.compare(0,origin.size(),origin)==0&&
                       (url[origin.size()]==L'/'||url[origin.size()]==L'?'||url[origin.size()]==L'#'));
}
bool NebulaRemote_EnsureReady(){++fixture::waits;return fixture::owned;}

namespace {
void reset(){g.once=INIT_ONCE{};g.original_get=nullptr;g.ready=false;g.public_config_present=false;g.origin.clear();
    fixture::api=fixture::profile=fixture::owned=true;fixture::gets=fixture::loads=fixture::waits=0;}
bool check(bool value,const char* label){if(!value){std::cerr<<"FAIL "<<label<<"\n";return false;}return true;}
void write(const std::filesystem::path& path,const std::vector<unsigned char>& value){std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(value.data()),static_cast<std::streamsize>(value.size()));if(!out)std::abort();}
void write(const std::filesystem::path& path,const std::string& value){write(path,std::vector<unsigned char>(value.begin(),value.end()));}
void* get(const std::wstring& url){
    std::vector<unsigned char> bytes(0x14+(url.size()+1)*sizeof(wchar_t));
    auto n=static_cast<std::int32_t>(url.size());std::memcpy(bytes.data()+0x10,&n,sizeof n);
    std::memcpy(bytes.data()+0x14,url.data(),url.size()*sizeof(wchar_t));
    return NebulaPublicAccess_Get(bytes.data(),fixture::wanted_info);
}
}
int main(int argc,char** argv){
    if(argc!=2)return 2;
    auto folder=std::filesystem::absolute(argv[1]).lexically_normal().make_preferred();if(std::filesystem::exists(folder))return 3;
    auto config_dir=folder/"NebulaPreservation";std::filesystem::create_directories(config_dir);fixture::local=folder.wstring();
    reset();if(!check(get(L"http://127.0.0.1:8080/local")==fixture::request&&fixture::gets==1&&fixture::loads==0,"unconfigured_local_forwards_original_once"))return 1;
    auto token=config_dir/"synthetic-token.bin";
    auto credential=std::string("Nebula-Account-v1 ")+std::string(23,'A')+'.'+std::string(43,'B');
    DATA_BLOB clear{static_cast<DWORD>(credential.size()),reinterpret_cast<BYTE*>(credential.data())},encrypted{};
    if(!CryptProtectData(&clear,nullptr,nullptr,nullptr,nullptr,CRYPTPROTECT_UI_FORBIDDEN,&encrypted))return 4;
    std::vector<unsigned char> bytes(8+encrypted.cbData);std::memcpy(bytes.data(),"NPA1",4);std::memcpy(bytes.data()+4,&encrypted.cbData,4);std::memcpy(bytes.data()+8,encrypted.pbData,encrypted.cbData);LocalFree(encrypted.pbData);write(token,bytes);
    auto config=config_dir/"public-access.conf";
    write(config,"format=nebula-public-access-v1\nserver_url=https://preservation.invalid:8443\ntoken_file="+token.string()+"\n");
    reset();if(!check(get(L"http://127.0.0.1:38080/N2UserExistServlet?frame=synthetic")==fixture::request&&g.ready&&fixture::loads==1&&fixture::waits==1&&fixture::gets==1,"stripped_engine_remote_loopback_should_forward"))return 1;
    reset();fixture::profile=false;if(!check(get(L"https://preservation.invalid:8443/N2UserExistServlet")==nullptr&&!g.ready&&fixture::gets==0,"configured_direct_https_fails_closed"))return 1;
    reset();fixture::owned=false;if(!check(get(L"http://127.0.0.1:38080/route")==nullptr&&fixture::waits==1&&fixture::gets==0,"unowned_or_unready_proxy_fails_closed"))return 1;
    for(const auto& url:{L"https://preservation.invalid:8443/route",L"http://localhost:38080/route",L"http://127.0.0.1:380801/route",L"http://127.0.0.2:38080/route"}){
        reset();if(!check(get(url)==nullptr&&fixture::waits==0&&fixture::gets==0,"nonexact_loopback_origin_rejected"))return 1;
    }
    reset();fixture::api=false;if(!check(get(L"http://127.0.0.1:38080/route")==nullptr&&fixture::gets==0,"missing_original_api_fails_closed"))return 1;
    write(token,"NPA1broken");reset();if(!check(get(L"http://127.0.0.1:38080/route")==nullptr&&fixture::loads==0&&fixture::gets==0,"invalid_synthetic_credential_fails_closed"))return 1;
    std::cout<<"TOTAL 10 actual consumer checks passed; stripped managed setters absent\n";
    return 0;
}
