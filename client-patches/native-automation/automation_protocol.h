#pragma once
// Fixed, allocation-free NAC1 parser. No target code is used by its tests.
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace nac {
enum Action : unsigned { Query=1, BackgroundOn=2, LoadNamed=3, LoginStart=4, WardrobeOpen=5, FrameCapture=6,
                         RemoveFemaleHat=7, SaveNamed=8, ShopOpenClothing=9,
                         ShopSelectTestFemaleTorso=10, ShopBuySelectedLocalCrystals=11, EconomyOpen=12, EconomySelectWardrobe=13, EconomySelectCompanion=14, EconomySelectLocomotion=15, EconomyBuyCrystals=16, EconomyBuyNP=17, SocialFriendRequest=18, SocialFriendAccept=19, SocialFavoriteOn=20, SocialFavoriteOff=21, SocialBlockOn=22, SocialBlockOff=23, SocialSilenceOn=24, SocialSilenceOff=25, SocialInvite=26, SocialInviteAccept=27, SocialTalk=28, SocialChatSend=29, SocialOpen=30, SocialShowFriends=31, SocialShowSpaceUsers=32, SocialShowSilenced=33, SocialShowBlocked=34, SocialSelectPeer=35, SocialShowNotifications=36, PublicChatShow=37, PublicChatSend=38, SettingsToggleNotification=39, SettingsTogglePlatform=40, SettingsOpen=41, CharacterExitSaved=42, Housing=200, ResourceCompanionSelect=203, ResourceCompanionRemove=204, ResourceLocomotionSelect=205, ResourceLocomotionRemove=206, ResourceCompanionPrepareSelect=207, ResourceCompanionPrepareRemove=208, ResourceLocomotionPrepareSelect=209, ResourceLocomotionPrepareRemove=210, MovementForward=201, MovementReverse=202 };
struct Command { uint32_t sequence{}; uint64_t deadline{}; Action action{}; char argument[65]{}; };
inline bool input_fits(uint64_t used, uint64_t incoming) {
    constexpr uint64_t limit=128*1024;
    return used<=limit && incoming<=limit-used;
}
inline bool decimal(const char *p, std::size_t n, uint64_t &out) {
    if (!n || (n>1 && p[0]=='0')) return false;
    out=0;
    for (std::size_t i=0;i<n;++i) {
        if(p[i]<'0'||p[i]>'9'||out>(UINT64_MAX-unsigned(p[i]-'0'))/10) return false;
        out=out*10+unsigned(p[i]-'0');
    }
    return true;
}
inline bool nonce_valid(const char *p, std::size_t n) {
    if(!p || n!=64) return false;
    for(std::size_t i=0;i<n;++i) if(!((p[i]>='0'&&p[i]<='9')||(p[i]>='a'&&p[i]<='f'))) return false;
    return true;
}
inline const char *action_name(Action a) {
    return a==MovementForward?"movement.forward":a==MovementReverse?"movement.reverse":a==ResourceCompanionSelect?"resource.companion.select":a==ResourceCompanionRemove?"resource.companion.remove":a==ResourceLocomotionSelect?"resource.locomotion.select":a==ResourceLocomotionRemove?"resource.locomotion.remove":a==ResourceCompanionPrepareSelect?"resource.companion.prepare_select":a==ResourceCompanionPrepareRemove?"resource.companion.prepare_remove":a==ResourceLocomotionPrepareSelect?"resource.locomotion.prepare_select":a==ResourceLocomotionPrepareRemove?"resource.locomotion.prepare_remove":a==Housing?"housing.command":a==Query?"query":a==BackgroundOn?"background-on":a==LoadNamed?"editor.load_named":a==LoginStart?"login.start":a==WardrobeOpen?"wardrobe.open":a==FrameCapture?"frame.capture":a==RemoveFemaleHat?"editor.remove_female_hat":a==SaveNamed?"editor.save_named":a==ShopOpenClothing?"shop.open_clothing":a==ShopSelectTestFemaleTorso?"shop.select_test_female_torso":a==ShopBuySelectedLocalCrystals?"shop.buy_selected_local_crystals":a==EconomyOpen?"shop.open":a==EconomySelectWardrobe?"shop.select_wardrobe_fixture":a==EconomySelectCompanion?"shop.select_companion_fixture":a==EconomySelectLocomotion?"shop.select_locomotion_fixture":a==EconomyBuyCrystals?"shop.buy_selected_crystals":a==EconomyBuyNP?"shop.buy_selected_np":a==SocialFriendRequest?"social.friend_request":a==SocialFriendAccept?"social.friend_accept":a==SocialFavoriteOn?"social.favorite_on":a==SocialFavoriteOff?"social.favorite_off":a==SocialBlockOn?"social.block_on":a==SocialBlockOff?"social.block_off":a==SocialSilenceOn?"social.silence_on":a==SocialSilenceOff?"social.silence_off":a==SocialInvite?"social.invite":a==SocialInviteAccept?"social.invite_accept":a==SocialTalk?"social.talk":a==SocialChatSend?"social.chat_send":a==SocialOpen?"social.open":a==SocialShowFriends?"social.show_friends":a==SocialShowSpaceUsers?"social.show_space_users":a==SocialShowSilenced?"social.show_silenced":a==SocialShowBlocked?"social.show_blocked":a==SocialSelectPeer?"social.select_peer":a==SocialShowNotifications?"social.show_notifications":a==PublicChatShow?"chat.show_public":a==PublicChatSend?"chat.send_public_test":a==SettingsToggleNotification?"settings.toggle_notification":a==SettingsTogglePlatform?"settings.toggle_platform":a==SettingsOpen?"settings.open":a==CharacterExitSaved?"editor.exit_saved":"invalid";
}
// All failures leave `out` untouched. Exact LF only, including final LF.
inline bool parse(const char *data, std::size_t size, const char nonce[65],
                  uint64_t now, uint32_t previous, Command &out) {
    if(!data || !size || size>2048 || !nonce_valid(nonce,64) || nonce[64]!=0 || data[size-1]!='\n') return false;
    const char *lines[6]{}; std::size_t lengths[6]{}; unsigned count=0; std::size_t start=0;
    for(std::size_t i=0;i<size;++i) {
        unsigned char c=static_cast<unsigned char>(data[i]);
        if(c=='\n') {
            if(count==6) return false;
            lines[count]=data+start; lengths[count++]=i-start; start=i+1;
        } else if(c<32 || c>126) return false;
    }
    if(count<5 || start!=size || lengths[0]!=4 || std::memcmp(lines[0],"NAC1",4) ||
       lengths[1]!=64 || std::memcmp(lines[1],nonce,64)) return false;
    uint64_t seq=0,deadline=0;
    if(!decimal(lines[2],lengths[2],seq)||seq<1||seq>256||seq<=previous ||
       !decimal(lines[3],lengths[3],deadline)||deadline<=now||deadline-now>120000) return false;
    Command candidate{}; candidate.sequence=static_cast<uint32_t>(seq); candidate.deadline=deadline;
    if(lengths[4]==5&&!std::memcmp(lines[4],"query",5)) candidate.action=Query;
    else if(lengths[4]==13&&!std::memcmp(lines[4],"background-on",13)) candidate.action=BackgroundOn;
    else if(lengths[4]==17&&!std::memcmp(lines[4],"editor.load_named",17)) candidate.action=LoadNamed;
    else if(lengths[4]==11&&!std::memcmp(lines[4],"login.start",11)) candidate.action=LoginStart;
    else if(lengths[4]==13&&!std::memcmp(lines[4],"wardrobe.open",13)) candidate.action=WardrobeOpen;
    else if(lengths[4]==13&&!std::memcmp(lines[4],"frame.capture",13)) candidate.action=FrameCapture;
    else if(lengths[4]==24&&!std::memcmp(lines[4],"editor.remove_female_hat",24)) candidate.action=RemoveFemaleHat;
    else if(lengths[4]==17&&!std::memcmp(lines[4],"editor.save_named",17)) candidate.action=SaveNamed;
    else if(lengths[4]==18&&!std::memcmp(lines[4],"shop.open_clothing",18)) candidate.action=ShopOpenClothing;
    else if(lengths[4]==29&&!std::memcmp(lines[4],"shop.select_test_female_torso",29)) candidate.action=ShopSelectTestFemaleTorso;
    else if(lengths[4]==32&&!std::memcmp(lines[4],"shop.buy_selected_local_crystals",32)) candidate.action=ShopBuySelectedLocalCrystals;
    else if(lengths[4]==9&&!std::memcmp(lines[4],"shop.open",9)) candidate.action=EconomyOpen;
    else if(lengths[4]==28&&!std::memcmp(lines[4],"shop.select_wardrobe_fixture",28)) candidate.action=EconomySelectWardrobe;
    else if(lengths[4]==29&&!std::memcmp(lines[4],"shop.select_companion_fixture",29)) candidate.action=EconomySelectCompanion;
    else if(lengths[4]==30&&!std::memcmp(lines[4],"shop.select_locomotion_fixture",30)) candidate.action=EconomySelectLocomotion;
    else if(lengths[4]==26&&!std::memcmp(lines[4],"shop.buy_selected_crystals",26)) candidate.action=EconomyBuyCrystals;
    else if(lengths[4]==20&&!std::memcmp(lines[4],"shop.buy_selected_np",20)) candidate.action=EconomyBuyNP;
    else if(lengths[4]==21&&!std::memcmp(lines[4],"social.friend_request",21)) candidate.action=SocialFriendRequest;
    else if(lengths[4]==20&&!std::memcmp(lines[4],"social.friend_accept",20)) candidate.action=SocialFriendAccept;
    else if(lengths[4]==18&&!std::memcmp(lines[4],"social.favorite_on",18)) candidate.action=SocialFavoriteOn;
    else if(lengths[4]==19&&!std::memcmp(lines[4],"social.favorite_off",19)) candidate.action=SocialFavoriteOff;
    else if(lengths[4]==15&&!std::memcmp(lines[4],"social.block_on",15)) candidate.action=SocialBlockOn;
    else if(lengths[4]==16&&!std::memcmp(lines[4],"social.block_off",16)) candidate.action=SocialBlockOff;
    else if(lengths[4]==17&&!std::memcmp(lines[4],"social.silence_on",17)) candidate.action=SocialSilenceOn;
    else if(lengths[4]==18&&!std::memcmp(lines[4],"social.silence_off",18)) candidate.action=SocialSilenceOff;
    else if(lengths[4]==13&&!std::memcmp(lines[4],"social.invite",13)) candidate.action=SocialInvite;
    else if(lengths[4]==20&&!std::memcmp(lines[4],"social.invite_accept",20)) candidate.action=SocialInviteAccept;
    else if(lengths[4]==11&&!std::memcmp(lines[4],"social.talk",11)) candidate.action=SocialTalk;
    else if(lengths[4]==16&&!std::memcmp(lines[4],"social.chat_send",16)) candidate.action=SocialChatSend;
    else if(lengths[4]==11&&!std::memcmp(lines[4],"social.open",11)) candidate.action=SocialOpen;
    else if(lengths[4]==19&&!std::memcmp(lines[4],"social.show_friends",19)) candidate.action=SocialShowFriends;
    else if(lengths[4]==23&&!std::memcmp(lines[4],"social.show_space_users",23)) candidate.action=SocialShowSpaceUsers;
    else if(lengths[4]==20&&!std::memcmp(lines[4],"social.show_silenced",20)) candidate.action=SocialShowSilenced;
    else if(lengths[4]==19&&!std::memcmp(lines[4],"social.show_blocked",19)) candidate.action=SocialShowBlocked;
    else if(lengths[4]==18&&!std::memcmp(lines[4],"social.select_peer",18)) candidate.action=SocialSelectPeer;
    else if(lengths[4]==25&&!std::memcmp(lines[4],"social.show_notifications",25)) candidate.action=SocialShowNotifications;
    else if(lengths[4]==16&&!std::memcmp(lines[4],"chat.show_public",16)) candidate.action=PublicChatShow;
    else if(lengths[4]==21&&!std::memcmp(lines[4],"chat.send_public_test",21)) candidate.action=PublicChatSend;
    else if(lengths[4]==28&&!std::memcmp(lines[4],"settings.toggle_notification",28)) candidate.action=SettingsToggleNotification;
    else if(lengths[4]==24&&!std::memcmp(lines[4],"settings.toggle_platform",24)) candidate.action=SettingsTogglePlatform;
    else if(lengths[4]==13&&!std::memcmp(lines[4],"settings.open",13)) candidate.action=SettingsOpen;
    else if(lengths[4]==17&&!std::memcmp(lines[4],"editor.exit_saved",17)) candidate.action=CharacterExitSaved;
    else if(lengths[4]==25&&!std::memcmp(lines[4],"resource.companion.select",25)) candidate.action=ResourceCompanionSelect;
    else if(lengths[4]==25&&!std::memcmp(lines[4],"resource.companion.remove",25)) candidate.action=ResourceCompanionRemove;
    else if(lengths[4]==26&&!std::memcmp(lines[4],"resource.locomotion.select",26)) candidate.action=ResourceLocomotionSelect;
    else if(lengths[4]==26&&!std::memcmp(lines[4],"resource.locomotion.remove",26)) candidate.action=ResourceLocomotionRemove;
    else if(lengths[4]==33&&!std::memcmp(lines[4],"resource.companion.prepare_select",33)) candidate.action=ResourceCompanionPrepareSelect;
    else if(lengths[4]==33&&!std::memcmp(lines[4],"resource.companion.prepare_remove",33)) candidate.action=ResourceCompanionPrepareRemove;
    else if(lengths[4]==34&&!std::memcmp(lines[4],"resource.locomotion.prepare_select",34)) candidate.action=ResourceLocomotionPrepareSelect;
    else if(lengths[4]==34&&!std::memcmp(lines[4],"resource.locomotion.prepare_remove",34)) candidate.action=ResourceLocomotionPrepareRemove;
    else if(lengths[4]==16&&!std::memcmp(lines[4],"movement.forward",16)) candidate.action=MovementForward;
    else if(lengths[4]==16&&!std::memcmp(lines[4],"movement.reverse",16)) candidate.action=MovementReverse;
    else if(lengths[4]==15&&!std::memcmp(lines[4],"housing.command",15)) candidate.action=Housing;
    else return false;
    if(candidate.action==Housing) {
        if(count!=6||lengths[5]<1||lengths[5]>64)return false;
        for(std::size_t j=0;j<lengths[5];++j)if(static_cast<unsigned char>(lines[5][j])<0x21||static_cast<unsigned char>(lines[5][j])>0x7e)return false;
        std::memcpy(candidate.argument,lines[5],lengths[5]);candidate.argument[lengths[5]]=0;
    } else if(candidate.action==LoadNamed||candidate.action==SaveNamed) {
        const std::size_t limit=candidate.action==SaveNamed?16:64;
        if(count!=6||lengths[5]<1||lengths[5]>limit) return false;
        std::memcpy(candidate.argument,lines[5],lengths[5]);
    } else if(count!=5) return false;
    out=candidate; return true;
}
}
