// Include after housing_native.inc and before publish. Query observation only.
// All pointers are reacquired on the current owner thread; none survive a query.
namespace peer_pose {
#include "appearance_core.inc"
struct DictionaryView {void* owner{};void* entries{};int count{},version{},free_count{};};
bool dictionary(void* value,int limit,DictionaryView& out) {
    out={};
    if(!typed(value,"Dictionary`2","System.Collections.Generic")||!readable(value,0x30))return false;
    out.owner=value;out.entries=field<void*>(value,0x18);out.count=field<int>(value,0x20);
    out.free_count=field<int>(value,0x28);out.version=field<int>(value,0x2c);
    if(out.count<0||out.count>limit||out.free_count<0||out.free_count>out.count)return false;
    if(!out.count)return !out.entries||readable(out.entries,0x20);
    if(!readable(out.entries,0x20))return false;
    auto length=field<uintptr_t>(out.entries,0x18);
    return length<=static_cast<uintptr_t>(limit)&&length>=static_cast<uintptr_t>(out.count)&&
        readable(out.entries,0x20+length*24);
}
bool unchanged(const DictionaryView& d){return field<void*>(d.owner,0x18)==d.entries&&
    field<int>(d.owner,0x20)==d.count&&field<int>(d.owner,0x28)==d.free_count&&field<int>(d.owner,0x2c)==d.version;}
void* entry(const DictionaryView& d,int i){return static_cast<char*>(d.entries)+0x20+size_t(i)*24;}
bool digest_text(const char* text,char out[65]) {
    nebula_movement::Digest digest{};
    if(!movement_sha(text,ULONG(std::strlen(text)),digest))return false;
    constexpr char hex[]="0123456789abcdef";
    for(unsigned i=0;i<32;++i){out[i*2]=hex[digest[i]>>4];out[i*2+1]=hex[digest[i]&15];}out[64]=0;return true;
}
struct Row {Appearance appearance{};uint32_t net_id{};char guid_sha256[65]{};float position[3]{};};
struct Observation {
    bool ready{};const char*reason="peer_pose_not_ready";uint32_t observer_net_id{},count{};
    uint64_t sampled_ms{};char instance[257]{},scene[257]{},observer_guid_sha256[65]{};
    Row rows[32]{};
};
bool collect(void* owner,Observation& out) {
    out=Observation{};out.reason="peer_pose_owner_guard";
    if(GetCurrentThreadId()!=thread||!initialized||disabled)return false;
    void* manager=nullptr;if(!housing_base_ready(owner,manager))return false;
    void* local=nullptr;auto network=observe_network(local);
    if(!network.probe_ok||!network.authenticated||!network.ready||!network.connection_ready||
       !typed(local,"NetworkIdentity","Mirror",true))return false;
    void* memory=field<void*>(manager,0x2c0);void* info=field<void*>(memory,0x10);
    out.observer_net_id=field<uint32_t>(local,0x28);
    char observer_guid[257]{};
    if(!out.observer_net_id||!managed_string(field<void*>(info,0x18),observer_guid,sizeof observer_guid)||
       !observer_guid[0]||!digest_text(observer_guid,out.observer_guid_sha256)||
       !managed_string(field<void*>(manager,0x248),out.instance,sizeof out.instance)||!out.instance[0]||
       !managed_string(field<void*>(manager,0x250),out.scene,sizeof out.scene)||!out.scene[0])return false;
    DictionaryView spawned{},remotes{};
    void* spawned_value=singleton(klass(mirror_image,"Mirror","NetworkClient"),"spawned");
    if(!dictionary(spawned_value,1024,spawned)||!dictionary(field<void*>(memory,0x18),256,remotes)){
        out.reason="peer_pose_dictionary_guard";return false;}
    // Verify our own exact identity is in the same current spawned dictionary.
    unsigned self_matches=0;int live_spawned=0;
    for(int i=0;i<spawned.count;++i){void* e=entry(spawned,i);if(field<int>(e,0)<0)continue;
        ++live_spawned;auto key=field<uint32_t>(e,8);void* identity=field<void*>(e,16);
        if(!key||!typed(identity,"NetworkIdentity","Mirror",true)||field<uint32_t>(identity,0x28)!=key){
            out.reason="peer_pose_spawn_identity_guard";return false;}
        if(key==out.observer_net_id){if(identity!=local)return false;++self_matches;}}
    if(self_matches!=1||live_spawned!=spawned.count-spawned.free_count)return false;
    int live_remotes=0;
    for(int i=0;i<remotes.count;++i){void* e=entry(remotes,i);if(field<int>(e,0)<0)continue;
        ++live_remotes;if(out.count>=32){out.reason="peer_pose_row_bound";return false;}
        void* remote=field<void*>(e,16);char key_guid[257]{},info_guid[257]{},player_guid[257]{};
        if(!typed(remote,"PlayerInfo","Assets.Scripts.Memories")||
           !managed_string(field<void*>(e,8),key_guid,sizeof key_guid)||!key_guid[0]||
           !managed_string(field<void*>(remote,0x18),info_guid,sizeof info_guid)||std::strcmp(key_guid,info_guid)||
           !std::strcmp(key_guid,observer_guid)){out.reason="peer_pose_remote_guid_guard";return false;}
        void* player=field<void*>(remote,0x30);uint32_t net_id{};
        if(!movement_player_info_net_id(remote,net_id)){out.reason="peer_pose_remote_netid_accessor_guard";return false;}
        void* identity=field<void*>(player,0xf8);
        if(!net_id||net_id==out.observer_net_id||!typed(player,"NebulaPlayer","",true)||!housing_active(player)||
           field<uint8_t>(player,0x9c)||!typed(identity,"NetworkIdentity","Mirror",true)||
           !field<uint8_t>(identity,0x18)||field<uint8_t>(identity,0x1a)||field<uint8_t>(identity,0x1b)||field<uint32_t>(identity,0x28)!=net_id||
           !managed_string(field<void*>(player,0xa0),player_guid,sizeof player_guid)||std::strcmp(key_guid,player_guid)){
            out.reason="peer_pose_remote_identity_guard";return false;}
        unsigned matches=0;
        for(int j=0;j<spawned.count;++j){void* se=entry(spawned,j);if(field<int>(se,0)<0)continue;
            if(field<uint32_t>(se,8)==net_id){if(field<void*>(se,16)!=identity)return false;++matches;}}
        if(matches!=1){out.reason="peer_pose_spawn_intersection_guard";return false;}
        void* transform=nullptr,*position=nullptr,*enabled=nullptr;
        void* nt=field<void*>(player,0x40);
        if(!typed(nt,"NetworkTransform","Mirror",true)||
           !invoke(method(klass(core_image,"UnityEngine","Behaviour"),"get_enabled",0,0x1b859f0),nt,nullptr,enabled)||
           !typed(enabled,"Boolean","System")||!field<uint8_t>(enabled,0x10)||
           !invoke(method(klass(core_image,"UnityEngine","Component"),"get_transform",0,0x1b85f10),player,nullptr,transform)||
           !typed(transform,"Transform","UnityEngine",true)||
           !invoke(method(klass(core_image,"UnityEngine","Transform"),"get_position",0,0x1b991e0),transform,nullptr,position)||
           !typed(position,"Vector3","UnityEngine")||!readable(position,0x1c)){
            out.reason="peer_pose_rendered_transform_guard";return false;}
        Row row{};appearance(player,row.appearance);row.net_id=net_id;if(!digest_text(key_guid,row.guid_sha256))return false;
        for(unsigned k=0;k<3;++k){row.position[k]=field<float>(position,0x10+k*4);if(!std::isfinite(row.position[k]))return false;}
        for(unsigned k=0;k<out.count;++k)if(out.rows[k].net_id==net_id||!std::strcmp(out.rows[k].guid_sha256,row.guid_sha256))return false;
        out.rows[out.count++]=row;
    }
    if(live_remotes!=remotes.count-remotes.free_count||!unchanged(spawned)||!unchanged(remotes)){
        out.reason="peer_pose_dictionary_changed";return false;}
    void* current_manager=nullptr;
    if(!housing_base_ready(owner,current_manager)||current_manager!=manager||
       field<void*>(manager,0x2c0)!=memory||field<void*>(memory,0x10)!=info||
       !housing_text_is(field<void*>(owner,0xe8),observer_guid)||!housing_text_is(field<void*>(info,0x18),observer_guid)||
       singleton(klass(mirror_image,"Mirror","NetworkClient"),"spawned")!=spawned.owner||
       field<void*>(memory,0x18)!=remotes.owner||
       !housing_text_is(field<void*>(manager,0x248),out.instance)||!housing_text_is(field<void*>(manager,0x250),out.scene))return false;
    out.sampled_ms=GetTickCount64();out.ready=true;out.reason="peer_pose_ready";return true;
}
void json(Json& j,void* owner){Observation ob{};bool ok=collect(owner,ob);
    j.append(",\"peer_pose\":{\"ready\":");j.boolean(ok);j.append(",\"reason\":");j.string(ob.reason);
    if(ok){j.append(",\"sampled_ms\":");j.integer(ob.sampled_ms);j.append(",\"instance_id\":");j.string(ob.instance);
        j.append(",\"psidglobal\":");j.string(ob.scene);j.append(",\"observer_net_id\":");j.integer(ob.observer_net_id);
        j.append(",\"observer_guid_sha256\":");j.string(ob.observer_guid_sha256);j.append(",\"rows\":[");
        for(unsigned i=0;i<ob.count;++i){if(i)j.append(",");auto&r=ob.rows[i];j.append("{\"net_id\":");j.integer(r.net_id);
            j.append(",\"guid_sha256\":");j.string(r.guid_sha256);j.append(",\"position\":[");
            for(unsigned k=0;k<3;++k){if(k)j.append(",");char number[48]{};std::snprintf(number,sizeof number,"%.9g",double(r.position[k]));j.append(number);}j.append("]");appearance_json(j,r.appearance);j.append("}");}j.append("]");}
    j.append("}");}
}
