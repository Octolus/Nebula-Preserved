#pragma once
#include <array>
#include <cstdint>
#include <cstring>
#include <limits>

// Registration is performed by NebulaPlayer.Start, independently of the TCP
// application queue. Never infer that registration from elapsed server frames.
namespace nebula_join_gate {
using Ptr = std::uintptr_t;
enum class Decision { Ready, Wait, Reject };
struct Epoch {
    std::int32_t manager{}, queue{};
    std::uint32_t local_net_id{};
    char guid[257]{}, instance[257]{};
    bool operator==(const Epoch& b) const {
        return manager == b.manager && queue == b.queue && local_net_id == b.local_net_id &&
            !std::strcmp(guid,b.guid) && !std::strcmp(instance,b.instance);
    }
};
struct Context { Epoch epoch{}; Ptr memory{}, spawned{}; bool local_ready{}; };
struct Transport {
    bool probe_ok{},connected{},authenticated{},ready{},connection_ready{};
    Ptr current_local_identity{};
};
inline bool transport_matches(const Transport& value,Ptr memory_local_identity) {
    return memory_local_identity&&value.probe_ok&&value.connected&&value.authenticated&&
        value.ready&&value.connection_ready&&value.current_local_identity==memory_local_identity;
}
struct Observation { Decision decision{Decision::Reject}; Epoch epoch{}; bool bound{}; };

template<class Host, class T> bool get(Host& h, Ptr p, std::size_t offset, T& out) {
    return p && offset <= std::numeric_limits<Ptr>::max()-p && h.read(p+offset,&out,sizeof out);
}
template<class Host> bool array(Host& h, Ptr value, std::uintptr_t limit, std::uintptr_t& count,bool outer=false) {
    Ptr bounds{};
    return h.type(value,outer?"String[][]":"String[]","System",false) && get(h,value,0x10,bounds) && !bounds &&
        get(h,value,0x18,count) && count<=limit && h.readable(value,0x20+count*sizeof(Ptr));
}
struct Dictionary {Ptr owner{}, entries{};std::int32_t count{}, free{}, version{};};
template<class Host> bool dictionary(Host& h,Ptr value,Dictionary& d) {
    d={};d.owner=value;std::uintptr_t length{};
    if(!h.type(value,"Dictionary`2","System.Collections.Generic",false) ||
       !get(h,value,0x18,d.entries)||!get(h,value,0x20,d.count)||
       !get(h,value,0x28,d.free)||!get(h,value,0x2c,d.version)||
       d.count<0||d.count>1024||d.free<0||d.free>d.count)return false;
    if(!d.count)return !d.entries||h.readable(d.entries,0x20);
    return get(h,d.entries,0x18,length)&&length<=1024&&length>=std::uintptr_t(d.count)&&
        h.readable(d.entries,0x20+length*24);
}
template<class Host> bool unchanged(Host& h,const Dictionary& d) {
    Ptr entries{};std::int32_t count{},free{},version{};
    return get(h,d.owner,0x18,entries)&&entries==d.entries&&get(h,d.owner,0x20,count)&&count==d.count&&
        get(h,d.owner,0x28,free)&&free==d.free&&get(h,d.owner,0x2c,version)&&version==d.version;
}
template<class Host> bool pending_registered(Host& h,const Dictionary& pending,const Dictionary& spawned,
    std::uint32_t wanted,std::uint32_t local,bool& yes) {
    yes=false;Ptr found{};unsigned matches=0;int live=0;
    for(int i=0;i<pending.count;++i){Ptr e=pending.entries+0x20+std::size_t(i)*24,player{},identity{};
        std::uint32_t key{},actual{};std::int32_t hash{};std::uint8_t is_local{},is_client{};
        if(!get(h,e,0,hash))return false;
        if(hash<0)continue;
        ++live;
        if(!get(h,e,8,key)||!key||!get(h,e,16,player)||!h.type(player,"NebulaPlayer","",true)||
           !get(h,player,0xf8,identity)||!h.type(identity,"NetworkIdentity","Mirror",true)||
           !get(h,identity,0x28,actual)||actual!=key||!get(h,identity,0x1a,is_local)||is_local||
           !get(h,identity,0x18,is_client)||!is_client||key==local)return false;
        if(key==wanted){found=identity;++matches;}
    }
    if(live!=pending.count-pending.free||matches>1)return false;
    unsigned spawned_matches=0;live=0;
    for(int i=0;i<spawned.count;++i){Ptr e=spawned.entries+0x20+std::size_t(i)*24,identity{};
        std::uint32_t key{},actual{};std::int32_t hash{};
        if(!get(h,e,0,hash))return false;
        if(hash<0)continue;
        ++live;
        if(!get(h,e,8,key)||!key||!get(h,e,16,identity)||!h.type(identity,"NetworkIdentity","Mirror",true)||
           !get(h,identity,0x28,actual)||actual!=key)return false;
        if(key==wanted){if(found&&found!=identity)return false;++spawned_matches;}
    }
    if(live!=spawned.count-spawned.free||spawned_matches>1)return false;
    yes=matches==1&&spawned_matches==1;return true;
}
inline bool uint32(const char* s,std::uint32_t& n) {
    n=0;if(!s||!*s)return false;
    for(unsigned i=0;s[i];++i){if(i>=10||s[i]<'0'||s[i]>'9')return false;
        unsigned d=unsigned(s[i]-'0');if(n>(UINT32_MAX-d)/10)return false;n=n*10+d;}return n!=0;
}
inline bool opcode32(const char* s,std::uint32_t& n) {
    if(s&&s[0]=='0'&&!s[1]){n=0;return true;}
    return s&&s[0]!='0'&&uint32(s,n)&&n<=INT32_MAX;
}
struct Seen {char guid[257]{};std::uint32_t net_id{};bool removed{};};
template<class Host> Observation observe(Host& h,Ptr queue) {
    Observation out{};Context context{};
    // Ownership context may already exist before Start. Failure to bind never
    // authorizes closing an unrelated connection, and never blocks no-join0.
    if(h.context(queue,context)){out.bound=true;out.epoch=context.epoch;}
    Ptr ring{},items{};std::int32_t head{},tail{},count{},version{};std::uintptr_t capacity{};
    if(!h.type(queue,"ProcessorQueue","Assets.Scripts.TCPs",true)||
       !get(h,queue,0x18,ring)||!h.type(ring,"Queue`1","System.Collections.Generic",false)||
       !get(h,ring,0x10,items)||!array(h,items,4096,capacity,true)||
       !get(h,ring,0x18,head)||!get(h,ring,0x1c,tail)||!get(h,ring,0x20,count)||
       !get(h,ring,0x24,version)||count<0||std::uintptr_t(count)>capacity||
       (capacity ? (head<0||tail<0||std::uintptr_t(head)>=capacity||std::uintptr_t(tail)>=capacity||
        std::uintptr_t(tail)!=(std::uintptr_t(head)+std::uintptr_t(count))%capacity) : (head||tail||count)))return out;
    bool has_join=false;
    for(int i=0;i<count;++i){Ptr message{},op{};std::uintptr_t fields{};char opcode[12]{};
        auto index=(std::uintptr_t(head)+std::uintptr_t(i))%capacity;
        std::uint32_t number{};
        if(!get(h,items,0x20+index*sizeof(Ptr),message)||!array(h,message,128,fields)||!fields||
           !get(h,message,0x20,op)||!h.text(op,opcode,sizeof opcode))return out;
        if(!opcode32(opcode,number))return out;
        if(!std::strcmp(opcode,"1"))has_join=true;
    }
    // Initial opcode0 drives local-avatar loading. Its own batch must remain
    // runnable before local Start/session probes become available.
    if(!has_join){out.decision=Decision::Ready;return out;}
    if(!out.bound)return out;
    if(!context.local_ready){out.decision=Decision::Wait;return out;}
    Dictionary pending{},remotes{},spawned{};Ptr p{},r{};
    if(!get(h,context.memory,0x28,p)||!dictionary(h,p,pending)||
       !get(h,context.memory,0x18,r)||!dictionary(h,r,remotes)||!dictionary(h,context.spawned,spawned))return out;
    std::array<Seen,128> seen{};std::array<std::uint32_t,128> consumed{};
    unsigned seen_count=0,consumed_count=0;bool waiting=false;
    for(int i=0;i<count;++i){Ptr message{},op{};std::uintptr_t fields{};char opcode[12]{};
        auto index=(std::uintptr_t(head)+std::uintptr_t(i))%capacity;
        std::uint32_t opcode_number{};
        if(!get(h,items,0x20+index*sizeof(Ptr),message)||!array(h,message,128,fields)||!fields||
           !get(h,message,0x20,op)||!h.text(op,opcode,sizeof opcode))return out;
        if(!opcode32(opcode,opcode_number))return out;
        if(std::strcmp(opcode,"1")&&std::strcmp(opcode,"14"))continue;
        const bool remove=!std::strcmp(opcode,"14");Ptr guid_object{},number_object{};char guid[257]{},number[12]{};
        if(fields!=(remove?2u:5u)||!get(h,message,remove?0x28:0x30,guid_object)||
           !h.text(guid_object,guid,sizeof guid)||!guid[0])return out;
        int at=-1;for(unsigned k=0;k<seen_count;++k)if(!std::strcmp(seen[k].guid,guid)){at=int(k);break;}
        if(at<0){if(seen_count>=seen.size())return out;at=int(seen_count++);std::memcpy(seen[at].guid,guid,sizeof guid);}
        if(remove){seen[at].removed=true;seen[at].net_id=0;continue;}
        std::uint32_t id{};
        if(!get(h,message,0x28,number_object)||!h.text(number_object,number,sizeof number)||!uint32(number,id))return out;
        bool exists=false;
        if(!h.known(context.memory,guid,exists))return out;
        // Exactly the original ContainsPlayer early-return, adjusted for earlier
        // queued removals and joins in the same original FIFO batch.
        if(!seen[at].removed&&(exists||seen[at].net_id))continue;
        for(unsigned k=0;k<consumed_count;++k)if(consumed[k]==id)return out;
        if(consumed_count>=consumed.size())return out;
        consumed[consumed_count++]=id;
        bool registered=false;
        if(!pending_registered(h,pending,spawned,id,context.epoch.local_net_id,registered))return out;
        if(!registered)waiting=true;
        seen[at].removed=false;seen[at].net_id=id;
    }
    Ptr check_ring{},check_items{};std::int32_t check_head{},check_tail{},check_count{},check_version{};Context after{};
    if(!h.context(queue,after)||!(after.epoch==context.epoch)||after.memory!=context.memory||after.spawned!=context.spawned||
       !get(h,queue,0x18,check_ring)||check_ring!=ring||!get(h,ring,0x10,check_items)||check_items!=items||
       !get(h,ring,0x18,check_head)||check_head!=head||!get(h,ring,0x1c,check_tail)||check_tail!=tail||
       !get(h,ring,0x20,check_count)||check_count!=count||!get(h,ring,0x24,check_version)||check_version!=version||
       !unchanged(h,pending)||!unchanged(h,remotes)||!unchanged(h,spawned))return out;
    out.decision=waiting?Decision::Wait:Decision::Ready;return out;
}
struct Guard {
    Epoch epoch{};bool set{},waiting{},failed{};std::uint64_t since{};
    Decision step(const Observation& o,std::uint64_t now) {
        // An unrelated unbound no-join queue cannot reset an owned deadline.
        if(o.decision==Decision::Ready&&!o.bound)return Decision::Ready;
        if(!o.bound)return Decision::Reject;
        if(!set||!(epoch==o.epoch)){epoch=o.epoch;set=true;waiting=false;failed=false;since=0;}
        if(failed)return Decision::Reject;
        if(o.decision==Decision::Reject){failed=true;return Decision::Reject;}
        if(o.decision==Decision::Ready){waiting=false;since=0;return Decision::Ready;}
        if(!waiting){waiting=true;since=now;}
        if(now<since||now-since>=10000){failed=true;return Decision::Reject;}
        return Decision::Wait;
    }
};
struct Statistics {
    std::uint64_t calls{},permits{},holds{},rejections{},closed{};
    // 0 idle, 1 ready, 2 registration wait, 3 invalid batch/epoch,
    // 4 wait expired, 5 initialization/profile refused, 6 thread refused.
    std::uint32_t reason{};
};
// Read-only same-main-thread diagnostics; no extra DLL export and no identity.
void statistics(Statistics& out) noexcept;
}
