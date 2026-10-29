// Inside peer_pose namespace. Read-only, no managed invocation, allocation,
// collection retention, transform writes, networking or speculative field repair.
struct Appearance {
    bool ready{},cap_present{},hat_object_present{},hat_object_active{};
    unsigned asset_count{},hat_asset_count{};int gender{-1};
    char assets_sha256[65]{};const char* reason="appearance_not_sampled";
};
bool appearance(void* player,Appearance& out){
    out={};out.gender=-1;out.reason="appearance_avatar_guard";
    void* avatar=field<void*>(player,0x18);
    if(!typed(avatar,"NebulaPlayerAvatar","Assets.Scripts.NebulaPlayers",true)||!readable(avatar,0x110)||
       field<void*>(avatar,0xf0)!=player)return false;
    if(field<uint8_t>(avatar,0x100)||!field<uint8_t>(avatar,0x101)){
        out.reason="appearance_construction_incomplete";return false;}
    out.gender=field<int>(avatar,0x104);if(out.gender<0||out.gender>1)return false;
    void* list=field<void*>(avatar,0x108);
    if(!typed(list,"List`1","System.Collections.Generic")||!readable(list,0x20))return false;
    void* items=field<void*>(list,0x10);auto count=field<int>(list,0x18),version=field<int>(list,0x1c);
    if(count<0||count>64||!readable(items,0x20))return false;
    auto capacity=field<uintptr_t>(items,0x18);
    if(capacity>128||capacity<static_cast<uintptr_t>(count)||!readable(items,0x20+capacity*16))return false;
    // AssetUser is a value type with name+0 / tablename+8; stride16 is pinned
    // by the metadata, not the stride of List<Object> or a boxed value.
    char canonical[16385]{};size_t used=0;
    for(int i=0;i<count;++i){
        void* row=static_cast<char*>(items)+0x20+size_t(i)*16;char name[129]{},table[129]{};
        if(!managed_string(field<void*>(row,0),name,sizeof name)||!name[0]||
           !managed_string(field<void*>(row,8),table,sizeof table)||!table[0])return false;
        size_t n=std::strlen(name),t=std::strlen(table);
        if(used+n+t+2>=sizeof canonical)return false;
        std::memcpy(canonical+used,name,n+1);used+=n+1;
        std::memcpy(canonical+used,table,t+1);used+=t+1;
        if(!std::strcmp(name,"AD5SPrEpGTolP62Jy4Ft7Sy1q00fgpfk"))out.cap_present=true;
        if(!std::strcmp(table,"CLOTH_HEAD_HAT"))++out.hat_asset_count;
    }
    if(out.hat_asset_count>1){out.reason="appearance_hat_asset_ambiguous";return false;}
    void* hat=field<void*>(avatar,0xe0);out.hat_object_present=hat!=nullptr;
    if(hat&&(!typed(hat,"GameObject","UnityEngine",true)||!active_hierarchy(hat,out.hat_object_active))){
        out.reason="appearance_hat_object_guard";return false;}
    if(field<void*>(avatar,0xf0)!=player||field<void*>(player,0x18)!=avatar||
       field<uint8_t>(avatar,0x100)||!field<uint8_t>(avatar,0x101)||
       field<void*>(avatar,0x108)!=list||field<void*>(list,0x10)!=items||
       field<int>(list,0x18)!=count||field<int>(list,0x1c)!=version||field<void*>(avatar,0xe0)!=hat)return false;
    nebula_movement::Digest hash{};if(!movement_sha(canonical,ULONG(used),hash))return false;
    constexpr char hex[]="0123456789abcdef";
    for(unsigned i=0;i<32;++i){out.assets_sha256[2*i]=hex[hash[i]>>4];out.assets_sha256[2*i+1]=hex[hash[i]&15];}
    out.assets_sha256[64]=0;out.asset_count=unsigned(count);out.ready=true;out.reason="appearance_constructed_assets_observed";return true;
}
void appearance_json(Json& j,const Appearance& out){
    j.append(",\"appearance\":{\"ready\":");j.boolean(out.ready);
    j.append(",\"reason\":");j.string(out.reason);
    if(out.ready){j.append(",\"gender\":");j.integer(unsigned(out.gender));
        j.append(",\"asset_count\":");j.integer(out.asset_count);j.append(",\"hat_asset_count\":");j.integer(out.hat_asset_count);
        j.append(",\"reviewed_cap_present\":");j.boolean(out.cap_present);
        j.append(",\"hat_object_present\":");j.boolean(out.hat_object_present);
        j.append(",\"hat_object_active\":");j.boolean(out.hat_object_active);
        j.append(",\"assets_sha256\":");j.string(out.assets_sha256);}
    j.append("}");
}
