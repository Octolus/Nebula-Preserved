> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Direct and legacy HTTP contracts

Static native analysis of Steam build 11018722. No game, client, server or connection test was run. Native pseudocode is not original C# source. Route literals do not prove runtime reachability or original server parity.

45 distinct route literals in 50 route/method occurrences. 33 names are outside the 40 task-route report. 33 direct contracts are recovered; remaining fields are explicitly pending in JSON.

## Preference and social codes

Key 15 (NameColorSelectedIndex) sends `{"x":r,"y":g,"z":b}`, produced by PlayerPrefsManager.set_nameColor at `0x180429950`. ColorData x/y/z are floats; the wire key is the enum name.

Social ListType: Friends 0, Silenced 1, Blocked 2, SpaceUsers 3, PSN 4. RelationType: None 0, Friend 1, Favorite 2, Ignored 3, SilentBy 4, BlockedUsers 5, UserBlockedBy 6. Status: Online 0, Away 1, Offline 2, Wardrobe 3.

Legacy N2GetSocialList sends `SessionGUID#PS4ID#type#typeFriendlist`. Menu calls send Friends (0,1), Silenced (1,1), Blocked (2,1). Response is `unused#unused#typeFriendlist#count#serializedEntry...`. TypeFriendlist 0 selects wardrobe/shop UI, 1 social UI. Entries deserialize as EntryData SocialListEntryModel: bool isFavourite, Status status, string name, int platform, ListType listType. They are not JSON. This differs from task GetSocialList.

## Recovered direct contracts

| Route | Request joined with # | Response / client behavior |
|---|---|---|
| CheckOwnGenericReward | `SessionGUID#PS4ID#idasset` | 0: unused; 1: unused; 2: unused; 3: already_owned; delimiter `#` |
| CinemaInteractionNPServlet | `SessionGUID#PS4ID#typeCinemaInteraction numeric` | 0: success_literal; 1: SessionGUID; 2: PS4ID; 3: success; delimiter `#` |
| GenericReward | `SessionGUID#PS4ID#idasset` | 0: unused; 1: unused; 2: unused; 3: reward_granted; delimiter `#` |
| GetCompanionsServlet | `SessionGUID#PS4ID` | 0: success_literal; 1: SessionGUID; 2..end: asset_IDs |
| GetConsumablePriceServlet | `SessionGUID#PS4ID#consumableID#tableID numeric` | 0: success_literal; 1: SessionGUID; 2: PS4ID; 3: consumableID; 4: unused; 5: price_display; 6: price_type_display; 7: user_amounts_display; 8: rewarded; delimiter `#` |
| GetConsumableServlet | `SessionGUID#PS4ID#consumableID#tableID numeric` | 0: success_literal; 1: SessionGUID; 2: PS4ID; 3: consumableID; 4: picnic_parsed_integer_or_unused; 5: success; 6: TCP_payload_value; 7: giveRewardIndex; delimiter `#` |
| GetInfoServlet (asset_catalog) | `0#SessionGUID#PS4ID#typeGender numeric#tablename#statusAsset` | 0: success_literal; 1: SessionGUID; 2: item_IDs; 3: status_values; 4: names; 5: id_types; 6: gender; delimiter `!` |
| GetInfoServlet (refresh_asset_catalog) | `0#SessionGUID#PS4ID#CE_Menu.typeGender numeric#MANAGEREditor field+0x168 category#MANAGEREditor field+0x170 status numeric` | Same seven-segment split and CW_Wardrobe catalog population as asset_catalog.; delimiter `!` |
| GetInfoServlet (current_preset_legacy) | `1#SessionGUID#PS4ID` | 0: success_literal; 1: SessionGUID; 2: unused; 3: preset; 4: gender; delimiter `#` |
| GetInfoServlet (last_used_preset_legacy) | `2#SessionGUID#PS4ID#typeGender numeric` | 0: success_literal; 1: SessionGUID; 2: preset; 3: gender; delimiter `#` |
| GetInfoServlet (named_preset_legacy) | `3#SessionGUID#PS4ID#typeGender numeric#presetname` | 0: success_literal; 1: SessionGUID; 2: preset; 3: idAssetsTablenames; delimiter `#` |
| GetLeaderboardServlet | `SessionGUID#PS4ID#typeFullGame enum NAME#stage numeric` | 0..end: rows; delimiter `#` |
| GetLocomotionsServlet | `SessionGUID#PS4ID` | 0: success_literal; 1: SessionGUID; 2..end: asset_IDs |
| GetPersonalSpacesServlet | `SessionGUID#PS4ID` | 0: success_literal; 1: SessionGUID; 2: PS4ID; 3: personal_space_names; delimiter `#` |
| GetSpaceEventServlet | `SessionGUID#PS4ID#psidglobal` | 0: unused; 1: unused; 2: event_available |
| GetrefusernameServlet | `SessionGUID#PS4ID#username` | 0: success_literal; 1: SessionGUID; 2: reference_GUID |
| InWardrobeCheckerServlet | `SessionGUID#PS4ID` | Body ignored |
| N2AddUser | `PS4Info.PS4ID#username#Mail#isPlayStationPlus#PS4Info.region.ToString() enum NAME#PS4Info.platform.ToString() numeric` | Body ignored |
| N2GetSocialList | `PS4Info.SessionGUID#PS4Info.PS4ID#type.ToString()#typeFriendlist.ToString()` | 0: unused_by_special_social_path; 1: unused_by_special_social_path; 2: typeFriendlist_UI_destination; 3: entry_count; 4..4+count-1: entries |
| N2GetUserTypeSpace | `SessionGUID#PS4ID#username#platform numeric` | 0: unused; 1: unused; 2: user_space_available |
| N2SavePreset | `SessionGUID#PS4ID#presetName#typeGender numeric#EntryData serialized preset` | 0: success_literal; 1: saved |
| RemoveInWardrobeServlet | `SessionGUID#PS4ID#PS4Info.spaceParams.id_instance` | Body ignored |
| RemovePresetServlet | `PS4Info.SessionGUID#PS4Info.PS4ID#presetname#currentPresetName#typeGender.ToString() numeric` | Body ignored |
| RenamePresetServlet | `PS4Info.SessionGUID#PS4Info.PS4ID#currentPresetLoadMenuName#presetrename#typeGender.ToString() numeric` | Body ignored |
| ReportServlet | `SessionGUID#PS4ID#optionReport numeric#targetName#text or literal 0 when empty` | 0: success_literal; 1: SessionGUID; 2: PS4ID; 3: accepted; delimiter `#` |
| RewardClothServlet | `SessionGUID#PS4ID#reward numeric` | 0: unused; 1: unused; 2: reward_granted; delimiter `#` |
| RewardConsumeServlet | `SessionGUID#PS4ID#idasset` | 0: success_literal; 1: SessionGUID; 2: PS4ID; delimiter `#` |
| SKLPromoServlet | `SessionGUID#PS4ID#id numeric` | 0: success_literal; 1: SessionGUID; 2: PS4ID; 3: sprite_id; delimiter `#` |
| SKLPromoTriggerServlet | `SessionGUID#PS4ID#id numeric` | 0: success_literal; 1: SessionGUID; 2: PS4ID; 3: already_available_or_consumed; delimiter `#` |
| SetLeaderboardServlet | `SessionGUID#PS4ID#typeFullGame enum NAME (ChronoRace)#value numeric#stage numeric` | Body ignored |
| SetPlayerPrefsServlet | `PS4Info.SessionGUID#PS4Info.PS4ID#PlayerPrefsKeys.ToString() enum NAME#value` | Body ignored |
| ShowPresetsServlet | `PS4Info.SessionGUID#PS4Info.PS4ID#typeGender.ToString() numeric` | 0: success_literal; 1: SessionGUID; 2..end: preset_names |
| WardrobeOptionItemServlet | `SessionGUID argument#sPS4ID argument#item argument#option argument#optional typeWardrobe argument when not empty` | 0: success_literal; 1: SessionGUID |
| XSpacesGamesType0Servlet | `SessionGUID#PS4ID#0 literal` | 0: success_literal; 1: SessionGUID; 2: PS4ID; 3: unused; 4: idReward; 5: isInserted; 6: cooldown; delimiter `#` |
| checkRewardAvailableServlet | `SessionGUID#PS4ID#Utils.RewardType enum NAME` | 0: success_literal; 1: SessionGUID; 2: available; delimiter `#` |
| checkRewardGameServlet | `SessionGUID#PS4ID#typeGame string#stage numeric` | 0: success_literal; 1: SessionGUID; 2: already_owned; delimiter `#` |
| checkStateNPFriendsServlet | `SessionGUID#PS4ID#zero or more PS4Info.NPFriends usernames as separate fields` | 0: success_literal; 1: SessionGUID; 2: unused; 3..end: username_status_pairs; delimiter `#` |

N2AddUser has no session prefix. It ignores the body and chains GUID generation when isNetworkError is false. ShowPresets consumes all trailing fields as names; no arbitrary trailer. Remove/Rename ignore their bodies and refresh ShowPresets. Legacy SetPlayerPrefsServlet includes PS4ID; modern SavePlayerPref omits it.

The legacy generic sender at `0x180414E40` checks true, SessionGUID and PS4ID for ordinary commands. It explicitly bypasses those checks for N2GetSocialList and passes that raw field array to its handler. It has no modern Contains(#) precheck.

## Active wardrobe listing and mutation

GetInfo mode 0 sends `0#GUID#PS4ID#genderInt#category#view` and receives seven segments separated by `!`: `true!GUID!IDs!statuses!displayNames!itemTypes!genderName`. The four item arrays inside those segments use `#`. The parser removes a first empty ID, skips empty integer entries, and directly indexes all parallel arrays by ID count. Empty inventory is `true!GUID!!!!!MALE` (or FEMALE): zero item tiles and one separate shop tile. Nonempty gender is required.

Request view is TypeWardrobe: 0 WARDROBE, 1 STORAGE, 2 DELETED. Returned item status is a different enum: 0 Favourite, 1 Normal, 2 Storage, 3 Deleted. Native UI flow supports server selection view 0 => statuses 0/1, view 1 => status 2, view 2 => status 3. Original server entitlement and SQL predicates remain unknown. CE_SubBtns defaults to view 0. RepaintWardrobe stores the view enum and sends that same view integer in the next mode 0 request.

Returned itemType codes are 0 Accessory, 1 Normal, 2 NormalEditable, 3 BigItem, 4 BigEditable, 5 Locomotion, 6 Animation, 7 FullBody, 8 PersonalSpace. paintAssets copies itemType to CW_Item; it is not an ownership flag. addAssets does no client-side ownership filtering. It always creates ImgShop, whose click invokes ShopManager.OpenShop separately from wardrobe items. The evidence supports an owned wardrobe inventory listing; original entitlement grants cannot be recovered from these consumers.

WardrobeOptionItemServlet option is the target item status: add/remove favourite sends 0/1, storage/restore sends 2/1, delete/restore sends 3/1. Selected tile name Img+itemID is stripped to raw itemID. Local typeOption 0/1/2 is not sent. Delete/restore includes the optional TypeWardrobe enum NAME, not its integer. On `true#GUID`, favourite actions update status, badge and sibling order locally; storage and delete actions close options and refresh the source view. Detailed branch effects and bounded native hashes are in JSON. Original persistence, authorization and invalid-transition behavior remain unproven.

## Consumable and cinema callback variants

GetConsumablePriceServlet uses the generic true/GUID/PS4ID prefix. Coffee and oktoberfest append `id#unused#price#priceType#userAmounts#rewardedBool` (minimum nine fields total); picnic appends `picnic#unused#price` (six total). Price, priceType and balance are display strings. Coffee/oktoberfest send table 0; picnic sends its selected trigger tableID.

GetConsumableServlet coffee/oktoberfest append `id#unused#successBool#TCPvalue#giveRewardIndexInt` (eight fields total). On success, callbacks send `44#GUID#coffee#TCPvalue` or `46#GUID#oktoberfest#TCPvalue` through TCPClient.Send. Picnic appends `picnic#parsedInt#successBool` (six total); its integer is parsed then discarded. The picnic success callback only obtains PicnicManager in its bounded native body.

CinemaInteractionNPServlet appends one success bool to the generic prefix. Type 0 Ticket sets cinemaFilms._isTicket; type 1 PopCorn sets _isPalomitas, then invokes OnGetCinemaInteractionNP. Original prices, balances, deductions, award choice, ticket duration and admission policy remain unproven.

## Route inventory

| Route | Native occurrence RVA(s) | Also in task report | Direct contract |
|---|---|---|---|
| ChannelGUIDServlet | `0x3f6fd0` | yes | pending |
| CheckOwnGenericReward | `0x3f7540` | no | recovered |
| CheckServerStatusServlet | `0x3f57e0` | yes | pending |
| CheckerServlet | `0x3f8a90` | yes | pending |
| CinemaInteractionNPServlet | `0x3ea1a0` | no | recovered |
| GenericReward | `0x3f9530` | no | recovered |
| GetCinemaFilmsServlet | `0x3f9c00` | yes | pending |
| GetCompanionsServlet | `0x3fa400` | no | recovered |
| GetConsumablePriceServlet | `0x3ea820` | no | recovered |
| GetConsumableServlet | `0x3eab80` | no | recovered |
| GetIinitInfosNeededServlet | `0x3fb570` | yes | pending |
| GetInfoServlet | `0x3dece0`, `0x3e0900`, `0x3df950`, `0x3e14d0`, `0x3d6f30` | no | recovered |
| GetLeaderboardServlet | `0x401860` | no | recovered |
| GetLocomotionsServlet | `0x3fbc20` | no | recovered |
| GetNewsServlet | `0x3fc410` | yes | pending |
| GetPersonalSpacesServlet | `0x3ecc10` | no | recovered |
| GetPlayerPrefsServlet | `0x3fcc40` | yes | pending |
| GetSpaceEventServlet | `0x3fd2b0` | no | recovered |
| GetrefusernameServlet | `0x3fabf0` | no | recovered |
| InWardrobeCheckerServlet | `0x3fe1b0` | no | recovered |
| InfoServlet | `0x3fe620` | yes | pending |
| N2AddUser | `0x3f6650` | no | recovered |
| N2GetSocialList | `0x3ecda0` | no | recovered |
| N2GetUserTypeSpace | `0x3fda10` | no | recovered |
| N2SavePreset | `0x3e3480`, `0x3e4220` | no | recovered |
| PlayerPrefsServlet | `0x3f7c10` | yes | pending |
| RemoveInWardrobeServlet | `0x415620` | no | recovered |
| RemovePresetServlet | `0x3e2520` | no | recovered |
| RenamePresetServlet | `0x3e2cd0` | no | recovered |
| ReportServlet | `0x3ed4c0` | no | recovered |
| ResetDefaultPresetServlet | `0x3e6cb0` | yes | pending |
| RewardClothServlet | `0x3ffd70` | no | recovered |
| RewardConsumeServlet | `0x3ed990` | no | recovered |
| SKLPromoServlet | `0x3ee1d0` | no | recovered |
| SKLPromoTriggerServlet | `0x3ede80` | no | recovered |
| SetLeaderboardServlet | `0x401100` | no | recovered |
| SetPlayerPrefsServlet | `0x3e7710` | no | recovered |
| ShowPresetsServlet | `0x3e5020` | no | recovered |
| UserExistsServlet | `0x3feda0` | yes | pending |
| WardrobeOptionItemServlet | `0x3e5a80` | no | recovered |
| XSpacesGamesType0Servlet | `0x3edcd0` | no | recovered |
| checkRewardAvailableServlet | `0x4161b0` | no | recovered |
| checkRewardGameServlet | `0x416a20` | no | recovered |
| checkStateNPFriendsServlet | `0x417b90` | no | recovered |
| spaceExistServlet | `0x3f80c0` | yes | pending |

## Unresolved work

Pending direct coroutine contracts need independent request/response reconstruction. Public wrappers sometimes use modern tasks while old coroutine bodies remain; native caller paths must establish reachability. Original backend state, authorization, scheduling and multi-user semantics remain unproven. No backend equivalence or launch readiness is claimed.
