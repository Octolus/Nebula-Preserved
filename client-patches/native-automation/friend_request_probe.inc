#include "friend_request_probe_policy.h"
struct SocialFriendRequestProbe { nebula::friend_request_probe::Inputs inputs{}; const char* reason{"friend_preflight_roots"}; std::int32_t selected_platform{-1},remote_platform{-1}; };
bool social_friend_request_probe(void* owner,std::uint8_t slot,SocialFriendRequestProbe& out){
 out={};void*manager=nullptr,*social=nullptr;const char*ignored=nullptr;
 out.inputs.roots=owner&&social_roots(manager,social,ignored);if(!out.inputs.roots)goto done;
 {void*main=field<void*>(social,0x20);out.inputs.main_window=typed(main,"SocialMainWindow","",true);void*loading=out.inputs.main_window?field<void*>(main,0x40):nullptr;out.inputs.loading_circle=typed(loading,"LoadingCircle","",true);}
 {void*model=nullptr;std::int32_t list=-1;out.inputs.selected_model=social_selected_model(social,slot,model,list,ignored);if(out.inputs.selected_model)out.selected_platform=field<std::int32_t>(model,0x28);}
 {void*peer=nullptr;out.inputs.peer=social_lookup_peer(manager,slot,peer,ignored)&&peer;void*memory=field<void*>(manager,0x2c0);void*guid=out.inputs.peer?field<void*>(peer,0xa0):nullptr;
  char expected[40]{},actual[64]{};void*name=nullptr,*name_args[]={guid};void*get_name=method(klass(script_image,"Assets.Scripts.Memories","Memory"),"GetUsername",1,0x610ce0);
  out.inputs.remote_username=typed(memory,"Memory","Assets.Scripts.Memories")&&guid&&social_peer_name(slot,expected)&&get_name&&invoke(get_name,memory,name_args,name)&&managed_string(name,actual,sizeof(actual))&&!std::strcmp(actual,expected);
  void*box=nullptr,*platform_args[]={guid};void*get_platform=method(klass(script_image,"Assets.Scripts.Memories","Memory"),"GetPlatform",1,0x610c80);
  out.inputs.remote_platform=out.inputs.remote_username&&get_platform&&invoke(get_platform,memory,platform_args,box)&&boxed_exact_return_int(box,get_platform,out.remote_platform)&&out.remote_platform==out.selected_platform;
  out.inputs.not_already_friend=out.inputs.peer&&!field<std::uint8_t>(peer,0xb8);SecureZeroMemory(expected,sizeof(expected));SecureZeroMemory(actual,sizeof(actual));}
 {void*ps4=singleton(klass(script_image,"","PS4Info"),"_singleton");char sender[64]{};out.inputs.local_sender=typed(ps4,"PS4Info","",true)&&managed_string(field<void*>(ps4,0xe0),sender,sizeof(sender))&&sender[0];SecureZeroMemory(sender,sizeof(sender));}
 {void*tcp=field<void*>(manager,0x2b8);out.inputs.tcp_client=typed(tcp,"TCPClient","TCPs",true);void*box=nullptr;bool connected=false;void*get_connected=method(klass(script_image,"TCPs","TCPClient"),"get_IsConnected",0,0x5e79f0);out.inputs.tcp_connected=out.inputs.tcp_client&&get_connected&&invoke(get_connected,tcp,nullptr,box)&&boxed_bool(box,connected)&&connected;}
done: out.reason=nebula::friend_request_probe::evaluate(out.inputs);return !std::strcmp(out.reason,"ready");
}
