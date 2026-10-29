// Included inside the existing helper's anonymous namespace AFTER observe_network.
// Uses the v16 core's actual API/type/lifetime/session readers, not caller proofs.
#include "movement_policy.h"
#include "movement_profile.h"
nebula_movement::Policy native_movement{};
bool movement_profile_checked{},movement_profile_ok{},movement_opt_in{};
std::uint64_t movement_step{},movement_generation{};
double movement_time{-1};
nebula_movement::Digest movement_binding{};
float movement_axes[2]{};
const char *movement_code="disabled";
const char *movement_snapshot_stage="not_sampled";
// Root's combined helper sets this from its actual economy/social/housing
// state machines on the same owner thread before servicing commands. It is
// internal, not an export or user-provided proof field.
std::uint32_t movement_shared_pending_mask{};
bool movement_pending() {
    const auto phase=native_movement.phase();
    return phase==nebula_movement::Phase::armed||phase==nebula_movement::Phase::moving||
           phase==nebula_movement::Phase::waiting_idle;
}

bool movement_sha(const void *data,ULONG count,nebula_movement::Digest &out) {
    BCRYPT_ALG_HANDLE alg{};
    if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0)return false;
    auto result=BCryptHash(alg,nullptr,0,reinterpret_cast<PUCHAR>(const_cast<void*>(data)),count,out.data(),32);
    BCryptCloseAlgorithmProvider(alg,0);return result>=0;
}
bool movement_disk_profile() {
    if(movement_profile_checked)return movement_profile_ok;
    movement_profile_checked=true;
    wchar_t path[1024]{},opt[4]{};
    movement_opt_in=GetEnvironmentVariableW(L"NEBULA_AUTOMATION_ALLOW_MOVEMENT",opt,4)==1&&opt[0]==L'1'&&!opt[1];
    if(!movement_opt_in||!GetModuleFileNameW(game,path,1024))return false;
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    BY_HANDLE_FILE_INFORMATION info{};bool okay=GetFileInformationByHandle(file,&info)&&
        !(info.dwFileAttributes&(FILE_ATTRIBUTE_REPARSE_POINT|FILE_ATTRIBUTE_DIRECTORY));
    BCRYPT_ALG_HANDLE alg{};BCRYPT_HASH_HANDLE hash{};unsigned char object[512]{},buffer[65536]{},sum[32]{};
    DWORD object_size=0,got=0;
    okay=okay&&BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0&&
        BCryptGetProperty(alg,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&object_size),sizeof(object_size),&got,0)>=0&&
        object_size<=sizeof(object)&&BCryptCreateHash(alg,&hash,object,object_size,nullptr,0,0)>=0;
    while(okay) {
        DWORD count=0;if(!ReadFile(file,buffer,sizeof(buffer),&count,nullptr)){okay=false;break;}
        if(!count)break;
        if(BCryptHashData(hash,buffer,count,0)<0){okay=false;break;}
    }
    if(okay)okay=BCryptFinishHash(hash,sum,32,0)>=0;
    if(hash)BCryptDestroyHash(hash);
    if(alg)BCryptCloseAlgorithmProvider(alg,0);
    CloseHandle(file);
    char hex[65]{};constexpr char digits[]="0123456789abcdef";
    for(unsigned i=0;i<32;++i){hex[i*2]=digits[sum[i]>>4];hex[i*2+1]=digits[sum[i]&15];}
    SecureZeroMemory(buffer,sizeof(buffer));SecureZeroMemory(object,sizeof(object));
    movement_profile_ok=okay&&!std::strcmp(hex,NEBULA_MOVEMENT_GAMEASSEMBLY_SHA256);return movement_profile_ok;
}
// Shipped PlayerInfo.get_NetId(616a70) follows nebulaPlayer.networkIdentity.netId.
// PlayerInfo's private +10 backing field remains zero in its shipped constructor.
bool movement_player_info_net_id(void *info,std::uint32_t &value) {
    value=0;
    if(GetCurrentThreadId()!=thread||!initialized||disabled||
       !typed(info,"PlayerInfo","Assets.Scripts.Memories"))return false;
    void *player=field<void*>(info,0x30);
    if(!typed(player,"NebulaPlayer","",true))return false;
    void *identity=field<void*>(player,0xf8);
    if(!typed(identity,"NetworkIdentity","Mirror",true)||!readable(identity,0x2c))return false;
    void *getter=method(klass(script_image,"Assets.Scripts.Memories","PlayerInfo"),"get_NetId",0,0x616a70),*box=nullptr;
    if(!invoke(getter,info,nullptr,box)||!typed(box,"UInt32","System")||!readable(box,0x14))return false;
    value=field<std::uint32_t>(box,0x10);
    return value&&value==field<std::uint32_t>(identity,0x28);
}
bool movement_snapshot(nebula_movement::Snapshot &s,bool axis=false,std::uint32_t site=0) {
    // This precedes EVERY IL2CPP call and pointer read. No foreign thread can
    // change policy or invoke a Unity getter through the exported axis entry.
    movement_snapshot_stage="runtime_profile_thread";
    if(!initialized||disabled||GetCurrentThreadId()!=thread||!movement_profile_ok)return false;
    s.thread_id=thread;s.now_ms=GetTickCount64();s.exact_profile=true;
    void *owner=singleton(klass(script_image,"","PS4Info"),"_singleton");
    movement_snapshot_stage="owner_type";
    if(!typed(owner,"PS4Info","",true))return false;
    s.current_singleton=true;
    char session[65]{},scene[1025]{},guid[257]{},owner_guid[257]{},info_guid[257]{},allocation[257]{},global[257]{};
    movement_snapshot_stage="session_or_scene";
    if(!session_digest(owner,session)||!active_scene(scene,sizeof(scene))||!scene[0])return false;
    s.world_scene=std::strcmp(scene,"Login")&&std::strcmp(scene,"PreInitiLOAD")&&
        std::strcmp(scene,"InitLOAD")&&std::strcmp(scene,"CharacterEditor")&&field<std::uint8_t>(owner,0xfa);
    void *manager=singleton(klass(script_image,"","ManagerInstance"),"_singleton");
    movement_snapshot_stage="manager_type";
    if(!derived_unity(manager,"ManagerInstance")||!readable(manager,0x2c8))return false;
    void *memory=field<void*>(manager,0x2c0),*info=field<void*>(memory,0x10),*player=field<void*>(info,0x30);
    movement_snapshot_stage="memory_info_player_type";
    if(!typed(memory,"Memory","Assets.Scripts.Memories")||!typed(info,"PlayerInfo","Assets.Scripts.Memories")||
       !typed(player,"NebulaPlayer","",true)||!readable(player,0x100))return false;
    void *identity=nullptr;auto network=observe_network(identity);
    s.authenticated=network.probe_ok&&network.authenticated;
    s.network_ready=network.connected&&network.ready&&network.connection_ready&&network.local_player_alive;
    s.current_local_player=field<std::uint8_t>(player,0x9c)&&field<void*>(player,0xf8)==identity;
    s.identity_owned=typed(identity,"NetworkIdentity","Mirror",true)&&readable(identity,0x2c)&&
        field<std::uint8_t>(identity,0x1a)&&field<std::uint8_t>(identity,0x1b);
    s.net_id=field<std::uint32_t>(identity,0x28);
    void *network_transform=field<void*>(player,0x40),*enabled_box=nullptr;
    void *enabled_method=method(klass(core_image,"UnityEngine","Behaviour"),"get_enabled",0,0x1b859f0);
    s.network_ready=s.network_ready&&typed(network_transform,"NetworkTransform","Mirror",true)&&
        invoke(enabled_method,network_transform,nullptr,enabled_box)&&typed(enabled_box,"Boolean","System")&&
        field<std::uint8_t>(enabled_box,0x10);
    movement_snapshot_stage="info_netid_accessor";
    std::uint32_t info_net_id{};if(!movement_player_info_net_id(info,info_net_id))return false;
    movement_snapshot_stage="guid_netid_or_allocation";
    if(!managed_string(field<void*>(player,0xa0),guid,sizeof(guid))||!guid[0]||
       !managed_string(field<void*>(owner,0xe8),owner_guid,sizeof(owner_guid))||!owner_guid[0]||
       !managed_string(field<void*>(info,0x18),info_guid,sizeof(info_guid))||!info_guid[0]||
       std::strcmp(guid,owner_guid)||std::strcmp(guid,info_guid)||info_net_id!=s.net_id||
       !managed_string(field<void*>(manager,0x248),allocation,sizeof(allocation))||!allocation[0]||
       !managed_string(field<void*>(manager,0x250),global,sizeof(global))||!global[0])return false;
    // Manager identity and Mirror netId bind the exact instance generation;
    // account/session digest and guid bind the authenticated player incarnation.
    char binding[2600]{};
    int length=std::snprintf(binding,sizeof(binding),"%s|%zu:%s|%zu:%s|%zu:%s|%zu:%s|%llu|%u",session,
        std::strlen(scene),scene,std::strlen(guid),guid,std::strlen(allocation),allocation,std::strlen(global),global,
        static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(manager)),s.net_id);
    movement_snapshot_stage="session_hash";
    if(length<=0||size_t(length)>=sizeof(binding)||!movement_sha(binding,ULONG(length),s.session))return false;
    SecureZeroMemory(binding,sizeof(binding));SecureZeroMemory(session,sizeof(session));SecureZeroMemory(guid,sizeof(guid));
    SecureZeroMemory(owner_guid,sizeof(owner_guid));SecureZeroMemory(info_guid,sizeof(info_guid));
    SecureZeroMemory(allocation,sizeof(allocation));SecureZeroMemory(global,sizeof(global));
    if(s.session!=movement_binding){movement_binding=s.session;++movement_generation;}
    s.generation=movement_generation;s.same_instance=field<std::uint8_t>(manager,0x121)&&!field<std::uint8_t>(manager,0x122);
    void *control=field<void*>(player,0x28),*input=field<void*>(player,0x60);
    movement_snapshot_stage="control_input_type";
    if(!typed(control,"NebulaPlayerControl","Assets.Scripts.NebulaPlayers",true)||!readable(control,0x65)||
       !typed(input,"NebulaInput","Assets.Scripts.NebulaPlayers",true)||!readable(input,0x54))return false;
    void *pad=field<void*>(control,0x38);
    movement_snapshot_stage="pad_type";
    if(!typed(pad,"PadPS4")||!readable(pad,0x12))return false;
    s.control=s.player_control=reinterpret_cast<std::uintptr_t>(control);
    s.pad=s.control_pad=reinterpret_cast<std::uintptr_t>(pad);
    s.singleton_pad=reinterpret_cast<std::uintptr_t>(singleton(klass(script_image,"","PadPS4"),"padPS4"));
    s.input_belongs_to_player=field<void*>(input,0x28)==control&&field<void*>(control,0x30)==player;
    s.input_available=field<std::uint8_t>(input,0x18)&&field<std::uint8_t>(input,0x53);
    s.initialized=field<std::uint8_t>(control,0x18);s.occupying=field<std::uint8_t>(control,0x64);
    s.controls_blocked=field<std::uint8_t>(pad,0x10);s.movement_blocked=field<std::uint8_t>(pad,0x11);
    s.manager_block_26e=field<std::uint8_t>(manager,0x26e);s.manager_block_270=field<std::uint8_t>(manager,0x270);
    if(axis&&site==0) {
        movement_snapshot_stage="fixed_time";
        // Time.timeAsDouble is fixedTime while called from original FixedUpdate.
        // Only the Move vertical seam advances this token; Pump never does.
        void *m=method(klass(core_image,"UnityEngine","Time"),"get_timeAsDouble",0,0x1b96060),*box=nullptr;
        if(!invoke(m,nullptr,nullptr,box)||!typed(box,"Double","System")||!readable(box,0x18))return false;
        double now=field<double>(box,0x10);
        if(!std::isfinite(now)||now<movement_time)return false;
        if(now>movement_time){movement_time=now;++movement_step;}
    }
    s.fixed_step=movement_step;
    // Original Anim writes VSpeed from original speed. Query its actual animator
    // parameter through fixed managed callbacks, never force an idle animation.
    if(!axis) {
    void *player_anim=field<void*>(player,0x38),*anim=nullptr,*box=nullptr;
    if(typed(player_anim,"NebulaPlayerAnim","Assets.Scripts.NebulaPlayers",true))
        anim=field<void*>(player_anim,0xb0);
    const std::uint16_t name[]={ 'V','S','p','e','e','d' };
    void *text=api.string_new_utf16(name,6);void *args[]={text};
    // Animator is TypeDef10261 in UnityEngine.AnimationModule, not CoreModule.
    // Resolve the class from this exact already-owned rendered Animator object.
    void *anim_class=typed(anim,"Animator","UnityEngine",true)?api.object_class(anim):nullptr;
    void *hash_method=method(anim_class,"StringToHash",1,0x1b62a30);
    if(text&&invoke(hash_method,nullptr,args,box)&&typed(box,"Int32","System")) {
        std::int32_t id=field<std::int32_t>(box,0x10);void *get_args[]={&id};
        void *get=method(anim_class,"GetFloat",1,0x1b62130);
        if(typed(anim,"Animator","UnityEngine",true)&&invoke(get,anim,get_args,box)&&typed(box,"Single","System"))
            s.ordinary_idle_observed=field<float>(control,0x40)==0&&field<float>(box,0x10)==0;
    }
    }
    movement_snapshot_stage="ready";
    return true;
}
const char *movement_start(const nac::Command &cmd,const char *&status) {
    if(!movement_disk_profile()){status="rejected";return "movement_profile_or_optin_guard";}
    if(preset_pending||remove_pending||save_pending||store_phase_pending()||movement_shared_pending_mask){status="rejected";return "movement_action_overlap";}
    nebula_movement::Snapshot s{};if(!movement_snapshot(s)){status="rejected";return "movement_snapshot_guard";}
    nebula_movement::Request r{};r.session=s.session;r.generation=s.generation;r.sequence=cmd.sequence;
    // Authenticated NAC1 command already consumed atomically by the existing
    // claimed-file path. Derive a unique nonce from its session nonce+sequence.
    char request_nonce[100]{};int n=std::snprintf(request_nonce,sizeof(request_nonce),"%s|%u",nonce,cmd.sequence);
    if(n<=0||!movement_sha(request_nonce,ULONG(n),r.nonce)){status="error";return "movement_nonce_hash";}
    r.deadline_ms=cmd.deadline;r.fixed_steps=30;
    r.direction=cmd.action==nac::MovementForward?nebula_movement::Direction::forward:nebula_movement::Direction::backward;
    if(!native_movement.arm(r,s,true)){status="rejected";return "movement_lease_guard";}
    movement_code="movement_armed";status="started";return movement_code;
}
void movement_service() {
    if(!movement_profile_ok)return;
    nebula_movement::Snapshot s{};
    if(!movement_snapshot(s)){native_movement.cancel();movement_axes[0]=movement_axes[1]=0;movement_code="movement_context_lost";return;}
    native_movement.observe(s);
    auto phase=native_movement.phase();
    if(phase==nebula_movement::Phase::waiting_idle||phase==nebula_movement::Phase::completed||phase==nebula_movement::Phase::cancelled)
        movement_axes[0]=movement_axes[1]=0;
    movement_code=phase==nebula_movement::Phase::completed?"movement_completed_idle":
        phase==nebula_movement::Phase::cancelled?"movement_cancelled":
        phase==nebula_movement::Phase::waiting_idle?"movement_waiting_original_idle":"movement_active";
}
void movement_json(Json &j) {
    j.append(",\"movement\":{\"phase\":");j.integer(static_cast<unsigned>(native_movement.phase()));
    j.append(",\"fixed_steps\":");j.integer(native_movement.frames_used());
    j.append(",\"code\":");j.string(movement_code);
    nebula_movement::Snapshot s{};
    if(movement_snapshot(s)) {
        j.append(",\"local_net_id\":");j.integer(s.net_id);
        j.append(",\"fixed_step\":");j.integer(s.fixed_step);
        j.append(",\"ordinary_idle_observed\":");j.boolean(s.ordinary_idle_observed);
        char hex[65]{};constexpr char digits[]="0123456789abcdef";
        for(unsigned i=0;i<32;++i){hex[2*i]=digits[s.session[i]>>4];hex[2*i+1]=digits[s.session[i]&15];}
        j.append(",\"session_digest\":");j.string(hex);
        auto number=[&j](float n) {char out[48]{};if(std::isfinite(n)){std::snprintf(out,sizeof(out),"%.9g",double(n));j.append(out);}else j.append("null");};
        j.append(",\"original_speed\":");number(field<float>(reinterpret_cast<void*>(s.control),0x40));
        j.append(",\"injected_axes\":[");number(movement_axes[0]);j.append(",");number(movement_axes[1]);j.append("]");
        void *get_transform=method(klass(core_image,"UnityEngine","Component"),"get_transform",0,0x1b85f10),*transform=nullptr,*box=nullptr;
        void *get_position=method(klass(core_image,"UnityEngine","Transform"),"get_position",0,0x1b991e0);
        if(invoke(get_transform,reinterpret_cast<void*>(s.control),nullptr,transform)&&
            typed(transform,"Transform","UnityEngine",true)&&invoke(get_position,transform,nullptr,box)&&
            typed(box,"Vector3","UnityEngine")&&readable(box,0x1c)) {
            j.append(",\"local_position\":[");number(field<float>(box,0x10));j.append(",");
            number(field<float>(box,0x14));j.append(",");number(field<float>(box,0x18));j.append("]");
        }
    }
    j.append(",\"snapshot_stage\":");j.string(movement_snapshot_stage);
    j.append(",\"profile_checked\":");j.boolean(movement_profile_checked);
    j.append(",\"profile_ok\":");j.boolean(movement_profile_ok);
    j.append(",\"opt_in\":");j.boolean(movement_opt_in);
    j.append("}");
}
