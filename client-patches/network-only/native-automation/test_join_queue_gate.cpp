#include "join_queue_gate.h"
#include <algorithm>
#include <functional>
#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
namespace g=nebula_join_gate;
using g::Ptr;
struct Block {Ptr start;std::vector<unsigned char> bytes;std::string name,space,text;};
struct Host {
    std::vector<Block> blocks;Ptr next=0x10000,queue{},ring{},pending{},remotes{},spawned{};
    g::Context ctx{};bool bound=true;unsigned context_calls=0,known_calls=0;
    std::function<void(Host&)> second_context;
    std::set<std::string> known_guids;std::set<std::uint32_t> native_pending;
    Ptr allocate(std::size_t size,const char* name="",const char* ns=""){
        Ptr id=next;next+=(size+0xff)&~Ptr(0xff);blocks.push_back({id,std::vector<unsigned char>(size),name,ns,{}});return id;}
    template<class T>void set(Ptr p,std::size_t off,T value){
        for(auto& b:blocks)if(p>=b.start&&p+off+sizeof value<=b.start+b.bytes.size()){
            std::memcpy(b.bytes.data()+p-b.start+off,&value,sizeof value);return;}throw std::runtime_error("fixture write");}
    bool readable(Ptr p,std::size_t n){for(auto& b:blocks)if(p>=b.start&&p+n<=b.start+b.bytes.size())return true;return false;}
    bool read(Ptr p,void* out,std::size_t n){for(auto& b:blocks)if(p>=b.start&&p+n<=b.start+b.bytes.size()){
        std::memcpy(out,b.bytes.data()+p-b.start,n);return true;}return false;}
    template<class T>T value(Ptr p,std::size_t off){T out{};if(!g::get(*this,p,off,out))throw std::runtime_error("fixture read");return out;}
    bool type(Ptr p,const char* name,const char* space,bool){
        for(auto& b:blocks)if(p==b.start)return b.name==name&&b.space==space;
        return false;}
    bool text(Ptr p,char* out,std::size_t n){for(auto& b:blocks)if(p==b.start&&b.name=="String"&&b.space=="System"){
        if(b.text.size()>=n)return false;
        std::memcpy(out,b.text.c_str(),b.text.size()+1);return true;}return false;}
    bool context(Ptr p,g::Context& out){++context_calls;if(context_calls==2&&second_context)second_context(*this);
        if(!bound||p!=queue)return false;
        out=ctx;return true;}
    bool known(Ptr memory,const char* guid,bool& yes){++known_calls;if(memory!=ctx.memory)return false;
        yes=known_guids.count(guid)!=0;return true;}
    Ptr str(const std::string& text){Ptr p=allocate(0x20,"String","System");blocks.back().text=text;return p;}
    Ptr array(const std::vector<Ptr>& entries,const char* name="String[]"){
        Ptr p=allocate(0x20+entries.size()*8,name,"System");set(p,0x18,std::uintptr_t(entries.size()));
        for(std::size_t i=0;i<entries.size();++i)set(p,0x20+i*8,entries[i]);
        return p;}
    Ptr message(std::initializer_list<const char*> strings){std::vector<Ptr> entries;
        for(auto s:strings)entries.push_back(str(s));
        return array(entries);}
    Ptr dict(const std::vector<std::pair<std::uint32_t,Ptr>>& rows={}){
        Ptr entries=allocate(0x20+rows.size()*24);set(entries,0x18,std::uintptr_t(rows.size()));
        for(std::size_t i=0;i<rows.size();++i){set(entries,0x20+i*24,std::int32_t(i));set(entries,0x28+i*24,rows[i].first);set(entries,0x30+i*24,rows[i].second);}
        Ptr p=allocate(0x30,"Dictionary`2","System.Collections.Generic");set(p,0x18,entries);set(p,0x20,std::int32_t(rows.size()));return p;}
    Ptr identity(std::uint32_t id,bool local=false){Ptr p=allocate(0x40,"NetworkIdentity","Mirror");
        set(p,0x18,std::uint8_t(1));set(p,0x1a,std::uint8_t(local));set(p,0x28,id);return p;}
    void register_players(std::initializer_list<std::uint32_t> ids){
        std::vector<std::pair<std::uint32_t,Ptr>> waiting,network{{1,identity(1,true)}};native_pending.clear();
        for(auto id:ids){Ptr ni=identity(id),player=allocate(0x110,"NebulaPlayer","");set(player,0xf8,ni);
            waiting.push_back({id,player});network.push_back({id,ni});native_pending.insert(id);}
        pending=dict(waiting);spawned=dict(network);ctx.spawned=spawned;set(ctx.memory,0x28,pending);
    }
    void batch(const std::vector<Ptr>& messages,int head=0,int extra=0){
        std::size_t capacity=messages.size()+std::size_t(extra);std::vector<Ptr> entries(capacity);
        for(std::size_t i=0;i<messages.size();++i)entries[(std::size_t(head)+i)%capacity]=messages[i];
        Ptr data=array(entries,"String[][]");ring=allocate(0x30,"Queue`1","System.Collections.Generic");
        set(ring,0x10,data);set(ring,0x18,std::int32_t(head));set(ring,0x1c,std::int32_t(capacity?(head+messages.size())%capacity:0));
        set(ring,0x20,std::int32_t(messages.size()));set(queue,0x18,ring);
    }
    Host(){queue=allocate(0x28,"ProcessorQueue","Assets.Scripts.TCPs");ctx.memory=allocate(0x40,"Memory","Assets.Scripts.Memories");
        ctx.epoch.manager=11;ctx.epoch.queue=22;ctx.epoch.local_net_id=1;ctx.local_ready=true;
        std::strcpy(ctx.epoch.guid,"local-guid");std::strcpy(ctx.epoch.instance,"fixture-instance");
        remotes=dict();set(ctx.memory,0x18,remotes);register_players({});batch({});}
    std::vector<std::vector<unsigned char>> bytes(){std::vector<std::vector<unsigned char>> result;for(auto& b:blocks)result.push_back(b.bytes);return result;}
    void native_drain(){ // Faithful relevant branches of retained 5e5010/5e43c0.
        auto count=value<std::int32_t>(ring,0x20),head=value<std::int32_t>(ring,0x18);Ptr arr=value<Ptr>(ring,0x10);
        auto capacity=value<std::uintptr_t>(arr,0x18);
        for(int i=0;i<count;++i){Ptr msg=value<Ptr>(arr,0x20+((head+i)%capacity)*8);char op[12]{},guid[257]{},num[12]{};
            text(value<Ptr>(msg,0x20),op,sizeof op);
            if(!std::strcmp(op,"14")){text(value<Ptr>(msg,0x28),guid,sizeof guid);known_guids.erase(guid);}
            if(std::strcmp(op,"1"))continue;
            text(value<Ptr>(msg,0x30),guid,sizeof guid);if(known_guids.count(guid))continue;
            text(value<Ptr>(msg,0x28),num,sizeof num);std::uint32_t id{};g::uint32(num,id);
            if(!native_pending.count(id))throw std::out_of_range("native remotesToBuild key");
            native_pending.erase(id);known_guids.insert(guid);
        }
    }
};
void need(bool okay,const char* message){if(!okay)throw std::runtime_error(message);}
unsigned checks=0;
void test(const char* name,const std::function<void()>& f){f();++checks;std::cout<<"PASS "<<name<<'\n';}
int main(){
    test("old eager drain fails before Start",[]{Host h;h.batch({h.message({"1","2","remote","name","1"})});
        bool failed=false;try{h.native_drain();}catch(const std::out_of_range&){failed=true;}need(failed,"old must fail");});
    test("registration wait retains exact original managed ring",[]{Host h;h.batch({h.message({"1","2","remote","name","1"})});
        auto before=h.bytes();auto ob=g::observe(h,h.queue);need(ob.decision==g::Decision::Wait,"must wait");need(before==h.bytes(),"queue mutated");});
    test("Start registration releases original once",[]{Host h;h.batch({h.message({"1","2","remote","name","1"})});
        need(g::observe(h,h.queue).decision==g::Decision::Wait,"must wait");h.register_players({2});
        need(g::observe(h,h.queue).decision==g::Decision::Ready,"not released");h.native_drain();need(h.known_guids.count("remote"),"original not reached");});
    test("empty queue requires no local Start or identity",[]{Host h;h.bound=false;h.ctx.local_ready=false;
        auto ob=g::observe(h,h.queue);g::Guard guard;need(guard.step(ob,1)==g::Decision::Ready,"empty blocked");});
    test("opcode0 local initialization stays runnable prebinding",[]{Host h;h.bound=false;h.batch({h.message({"0"})});
        g::Guard guard;need(guard.step(g::observe(h,h.queue),1)==g::Decision::Ready,"opcode0 deadlock");});
    test("pre-Start owned join waits with bounded epoch",[]{Host h;h.ctx.local_ready=false;h.ctx.epoch.local_net_id=0;
        h.batch({h.message({"0"}),h.message({"1","2","remote","name","1"})});
        auto ob=g::observe(h,h.queue);g::Guard guard;need(guard.step(ob,50)==g::Decision::Wait,"not prestart wait");
        need(guard.step(ob,10050)==g::Decision::Reject,"unbounded local wait");});
    test("ring wrap and late join both checked",[]{Host h;h.batch({h.message({"10","ignored","1"}),h.message({"1","2","remote","name","1"})},3,2);
        need(g::observe(h,h.queue).decision==g::Decision::Wait,"late join missed");h.register_players({2});
        need(g::observe(h,h.queue).decision==g::Decision::Ready,"wrapped join not released");h.native_drain();});
    test("multiple joins wait for every independent registration",[]{Host h;h.batch({h.message({"1","2","a","A","1"}),h.message({"1","3","b","B","1"})});
        h.register_players({2});need(g::observe(h,h.queue).decision==g::Decision::Wait,"second missing registration ignored");
        h.register_players({2,3});need(g::observe(h,h.queue).decision==g::Decision::Ready,"both ready");h.native_drain();need(h.known_guids.size()==2,"not both native loaded");});
    test("original ContainsPlayer early-return accepted",[]{Host h;h.known_guids.insert("known");h.batch({h.message({"1","22","known","name","1"})});
        need(g::observe(h,h.queue).decision==g::Decision::Ready&&h.known_calls==1,"native predicate not used");h.native_drain();});
    test("same GUID duplicate consumes pending only once",[]{Host h;h.register_players({2});h.batch({h.message({"1","2","a","A","1"}),h.message({"1","2","a","A","1"})});
        need(g::observe(h,h.queue).decision==g::Decision::Ready,"duplicate blocked");h.native_drain();});
    test("remove before rejoin invalidates initial known shortcut",[]{Host h;h.known_guids.insert("a");h.batch({h.message({"14","a"}),h.message({"1","2","a","A","1"})});
        need(g::observe(h,h.queue).decision==g::Decision::Wait,"known shortcut survived remove");});
    test("remove and rejoin cannot consume same registration twice",[]{Host h;h.register_players({2});h.batch({h.message({"1","2","a","A","1"}),h.message({"14","a"}),h.message({"1","2","a","A","1"})});
        need(g::observe(h,h.queue).decision==g::Decision::Reject,"double consumption escaped");});
    test("remove and rejoin distinct new registration valid",[]{Host h;h.register_players({2,3});h.batch({h.message({"1","2","a","A","1"}),h.message({"14","a"}),h.message({"1","3","a","A","1"})});
        need(g::observe(h,h.queue).decision==g::Decision::Ready,"distinct rejoin blocked");h.native_drain();});
    test("two GUIDs cannot consume same pending netID",[]{Host h;h.register_players({2});h.batch({h.message({"1","2","a","A","1"}),h.message({"1","2","b","B","1"})});
        need(g::observe(h,h.queue).decision==g::Decision::Reject,"conflicting aliases");});
    test("invalid tail bound rejects owned batch",[]{Host h;h.batch({h.message({"1","2","a","A","1"})});h.set(h.ring,0x1c,std::int32_t(7));
        auto ob=g::observe(h,h.queue);need(ob.bound&&ob.decision==g::Decision::Reject,"bad tail accepted");});
    test("wrong array class rejected",[]{Host h;h.batch({h.message({"1","2","a","A","1"})});Ptr arr=h.value<Ptr>(h.ring,0x10);
        for(auto& b:h.blocks)if(b.start==arr)b.name="Int32[]";
        need(g::observe(h,h.queue).decision==g::Decision::Reject,"array generic shape guessed");});
    test("invalid netID parse rejected",[]{for(const char* id:{"0","-1","4294967296","xx",""}){Host h;h.batch({h.message({"1",id,"a","A","1"})});
        need(g::observe(h,h.queue).decision==g::Decision::Reject,"invalid ID accepted");}});
    test("noncanonical Int32 opcode aliases cannot bypass gate",[]{for(const char* op:{"01","+1"," 1","1 ","014","2147483648","-1"}){Host h;
        h.batch({h.message({op,"2","a","A","1"})});need(g::observe(h,h.queue).decision==g::Decision::Reject,"opcode alias bypass");}});
    test("missing exact join fields rejected",[]{Host h;h.batch({h.message({"1","2","a"})});need(g::observe(h,h.queue).decision==g::Decision::Reject,"bad field count");});
    test("pending player identity mismatch rejected",[]{Host h;h.register_players({2});h.batch({h.message({"1","2","a","A","1"})});
        auto entries=h.value<Ptr>(h.pending,0x18);Ptr player=h.value<Ptr>(entries,0x30),ni=h.value<Ptr>(player,0xf8);h.set(ni,0x28,std::uint32_t(3));
        need(g::observe(h,h.queue).decision==g::Decision::Reject,"NI mismatch accepted");});
    test("spawned registration must reference same identity",[]{Host h;h.register_players({2});h.batch({h.message({"1","2","a","A","1"})});
        auto entries=h.value<Ptr>(h.spawned,0x18);h.set(entries,0x20+24+16,h.identity(2));need(g::observe(h,h.queue).decision==g::Decision::Reject,"wrong identity intersection");});
    test("observation invalidated by queue version change",[]{Host h;h.register_players({2});h.batch({h.message({"1","2","a","A","1"})});
        h.second_context=[](Host& x){x.set(x.ring,0x24,std::int32_t(1));};need(g::observe(h,h.queue).decision==g::Decision::Reject,"version race accepted");});
    test("observation invalidated by session replacement",[]{Host h;h.register_players({2});h.batch({h.message({"1","2","a","A","1"})});
        h.second_context=[](Host& x){std::strcpy(x.ctx.epoch.guid,"replacement");};need(g::observe(h,h.queue).decision==g::Decision::Reject,"session race accepted");});
    test("append and repeated updates do not extend original deadline",[]{Host h;h.batch({h.message({"1","2","a","A","1"})});g::Guard guard;
        need(guard.step(g::observe(h,h.queue),100)==g::Decision::Wait,"initial wait");
        h.batch({h.message({"1","2","a","A","1"}),h.message({"10","x","0"})});
        need(guard.step(g::observe(h,h.queue),10099)==g::Decision::Wait,"early expiration");
        need(guard.step(g::observe(h,h.queue),10100)==g::Decision::Reject,"deadline extended");});
    test("actual new session resets failed wait",[]{Host h;h.batch({h.message({"1","2","a","A","1"})});g::Guard guard;auto ob=g::observe(h,h.queue);
        guard.step(ob,1);need(guard.step(ob,10001)==g::Decision::Reject,"expected expired");
        std::strcpy(h.ctx.epoch.guid,"new-session");need(guard.step(g::observe(h,h.queue),10002)==g::Decision::Wait,"new epoch stuck");});
    test("unrelated unbound queue cannot extend owned deadline",[]{Host h;h.batch({h.message({"1","2","a","A","1"})});g::Guard guard;
        auto owned=g::observe(h,h.queue);need(guard.step(owned,1)==g::Decision::Wait,"initial owned wait");
        Host unrelated;unrelated.bound=false;auto unbound=g::observe(unrelated,unrelated.queue);
        need(guard.step(unbound,9999)==g::Decision::Ready,"unbound no-join blocked");
        need(guard.waiting&&guard.since==1&&guard.epoch==owned.epoch,"bound deadline was reset");
        need(guard.step(owned,10001)==g::Decision::Reject,"unrelated queue extended deadline");});
    test("bound empty batch clears its own earlier wait",[]{Host h;h.batch({h.message({"1","2","a","A","1"})});g::Guard guard;
        auto owned=g::observe(h,h.queue);guard.step(owned,1);h.batch({});
        need(guard.step(g::observe(h,h.queue),9999)==g::Decision::Ready,"bound no-join stuck");need(!guard.waiting&&guard.since==0,"bound timer retained");});
    test("current Mirror local matches exact Memory local",[]{g::Transport t{true,true,true,true,true,0x1234};
        need(g::transport_matches(t,0x1234),"current NI refused");});
    test("stale Memory NI cannot borrow new connection readiness",[]{g::Transport t{true,true,true,true,true,0x1234};
        need(!g::transport_matches(t,0x5678),"stale NI accepted");});
    test("pending transport hydration keeps local not ready",[]{g::Transport t{true,true,true,true,true,0x1234};
        t.current_local_identity=0;need(!g::transport_matches(t,0x1234),"null local accepted");
        t.current_local_identity=0x1234;t.connection_ready=false;need(!g::transport_matches(t,0x1234),"unready connection accepted");
        t.connection_ready=true;t.authenticated=false;need(!g::transport_matches(t,0x1234),"unauthenticated accepted");
        t.authenticated=true;t.ready=false;need(!g::transport_matches(t,0x1234),"unready network accepted");
        t.ready=true;t.connected=false;need(!g::transport_matches(t,0x1234),"disconnected accepted");
        t.connected=true;t.probe_ok=false;need(!g::transport_matches(t,0x1234),"missing probe accepted");});
    std::cout<<"TOTAL "<<checks<<" checks passed\n";
}
