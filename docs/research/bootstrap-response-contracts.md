> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Bootstrap response contracts

Static analysis of Steam build 11018722, GameAssembly SHA256 `c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac`. No game, client, or server launched for this analysis. This records client acceptance rules, not original backend equivalence.

All 40 HTTP task routes with recovered command literals have response contracts below. Exact request order is recovered for all 40. The JSON companion includes full native addresses, signatures, byte-window hashes, DTO declarations and explicit unknowns.

## Shared framing

Decrypted text must contain `#`. `String.Split('#', StringSplitOptions.None)` keeps trailing empty fields. There is no universal success prefix or removed trailer. Some routes need a trailer; other routes consume every field or require an exact length. Native evidence: `HTTPSender.ProcessResponse0x18060FFC0`.

## Bootstrap path

| Route | Decrypted task field order | Native effect |
|---|---|---|
| STMGetUserInfo | `unused#{Steam JSON}X` | Removes final character from field 1, then SteamManager parses JSON. |
| CheckerServlet | `unused#{request nonce}#false#{ban date}#{ban description}` | Matching nonce and false ban continues. |
| CheckServerStatusServlet | `true#{request username}#{request nonce}#1` | Status 1 continues; 0 maintenance; 2 patch scene. |
| N2UserExist | `{PS4ID}##{remembered login}#false#false##` | Minimum 7; wrong PS4ID calls Quit. Login value also fills remembered password. |
| ChannelGUIDServlet | `true#` | Client generates SessionGUID before request; a response GUID would be unused. |
| GetIinitInfosNeededServlet | `{SessionGUID}#{bool}[#{bool}[#{bool}]]` | No true prefix. Sets empty-GUID check, preset validation, memorion flags. |
| GetPlayerPrefsServlet | `true#{SessionGUID}#{PlayerPrefsJson}` | Applies player prefs. |
| GetCinemaFilmsServlet | `{SessionGUID}#{hour}#{minute}#{second}#{maxMinutes}[#{film}#{seconds}]*` | No true prefix; all extra fields are pairs. |
| GetPurchases | `true#{SessionGUID}#{PurchasesData JSON}` | Adds purchased assets. |
| GetLastUsedPreset | `true#{local PS4ID}#{gender}#{preset JSON}#{id assets JSON}#{position JSON}` | Builds AvatarInfo; MALE chooses male type. |
| N2AddUserOnline | `unused#{bool}` | Passes bool to login callback. |
| N2LoadSpace | `{SessionGUID}#{banned bool}#{noFreeSlot bool}` | Both false starts space polling. |
| N2SpaceLoading | `{SessionGUID}#true#{id_space}#{psidglobal}#{ip}#{port}` | Calls JoinSpace with maxusers 32; false ready retries. |

Templates are parser-compatible shapes. Candidate defaults and account semantics remain unverified.

## Session identity

`HTTPGenerateGUID.Process` at `0x180607FC0` computes `H=SHA256_ASCII_LOWERHEX(DateTime.Now.ToString())`, then stores `SHA256_ASCII_LOWERHEX(PS4ID+"#"+H).Substring(0,32)` as `PS4Info.SessionGUID`. Request is `PS4ID#H`. Success launches three tasks and immediately calls its caller; it does not wait for preference/init/cinema replies.

## JSON shapes

The JSON companion includes all 22 PlayerPrefsJson fields, all 27 PurchasesData fields, all 450 male preset fields, all 462 female preset fields, housing arrays, player label, Steam response types and player preference enum values. Layout offsets are evidence for native field matching, not wire offsets.

LastPosJson keys: `GUID`, `PS4ID`, `lastPosition_x`, `lastPosition_y`, `lastPosition_z`. IdAssetsTablenamesJson has string `data`. Social JSON has `lUsernames` string list.

Preset item strings are compared against the literal string `"null"`. Missing keys can produce managed null values which still enter item lists. An empty JSON object is not a verified default avatar. Valid IDs and body/face values need shipped-content evidence.

## Complete task route inventory

| Route | OnResponse VA | Request order | Response fields |
|---|---|---|---|
| N2AddBlock | `0x180605e80` | recovered | 0:unused; 1:result |
| N2AddSilenced | `0x1806062d0` | recovered | 0:unused; 1:result |
| CheckerServlet | `0x1806074a0` | recovered | 0:unused; 1:time_nonce_echo; 2:isBanned; 3:banDate; 4:banDescription |
| Send_CheckIsInWardrobeServlet | `0x180606720` | recovered | 0:unused; 1:SessionGUID; 2:unused; 3:isInWardrobe; 4:required_unused_trailer |
| PlayerPrefsServlet | `0x1803c3950` | recovered | array ignored |
| spaceExistServlet | `0x180606de0` | recovered | 0:success_literal; 1:SessionGUID; 2:exists |
| ChannelGUIDServlet | `0x180607c20` | recovered | 0:success_literal |
| GetAllInWardrobe | `0x180608270` | recovered | 0:unused; 1:items; length-1:unused_trailer |
| GetCinemaFilmsServlet | `0x1806085d0` | recovered | 0:SessionGUID; 1:hour; 2:minute; 3:second; 4:maxMinutes; 5:pair sequence |
| GetIinitInfosNeededServlet | `0x180608b20` | recovered | 0:SessionGUID; 1:isplayerguidEmptyCheckActive; 2:isValidateCachedPresetActive; 3:isMemorionActive |
| GetLastUsedPreset | `0x180608f70` | recovered | 0:success_literal; 1:local_PS4ID; 2:gender; 3:preset; 4:idAssetsTablenames; 5:lastPosition |
| GetLoadPresetByName | `0x180619e00` | recovered | 0:success_literal; 1:local_PS4ID; 2:gender; 3:preset; 4:idAssetsTablenames; 5:lastPosition |
| GetNewsServlet | `0x1806217e0` | recovered | 0:count; 1:pair sequence |
| PlayerLabelInfoServlet | `0x180621c10` | recovered | 0:success_literal; 1:SessionGUID; 2:local_PS4ID; 3:targetGUID; 4:label; 5:optional_extra_label_string |
| GetPlayerPrefsServlet | `0x180622390` | recovered | 0:success_literal; 1:SessionGUID; 2:preferences |
| GetPresetGameServlet | `0x180622740` | recovered | 0:success_literal; 1:local_PS4ID; 2:gender; 3:preset; 4:idAssetsTablenames; 5:lastPosition |
| GetPurchases | `0x180634fb0` | recovered | 0:success_literal; 1:SessionGUID; 2:purchases |
| N2GetRelationship | `0x180635300` | recovered | 0:unused; 1:unused; 2:unused; 3:unused; 4:relationship |
| GetSocialList | `0x180635700` | recovered | 0:unused; 1:listSocial |
| N2RemoveBlock | `0x180637730` | recovered | 0:unused; 1:result |
| N2RemoveFriend | `0x180637b80` | recovered | 0:unused; 1:result |
| N2RemoveSilenced | `0x180637fd0` | recovered | 0:unused; 1:result |
| ResetDefaultPresetServlet | `0x180638490` | recovered | array ignored |
| SavePlayerPref | `0x1806399f0` | recovered | 0:success_literal; 1:SessionGUID |
| InfoServlet | `0x1803c3950` | recovered | array ignored |
| CheckServerStatusServlet | `0x18063abc0` | recovered | 0:success_literal; 1:userName_echo; 2:time_nonce_echo; 3:status |
| SetUserInWardrobe | `0x18063afe0` | recovered | 0:unused; 1:result |
| STMBuyCrystals | `0x18035a740` | recovered | array ignored |
| STMCompleteOrder | `0x180639030` | recovered | 0:unused; 1:display_result |
| STMCompleteSucceededOrders | `0x18035a740` | recovered | array ignored |
| STMGetUserInfo | `0x180639790` | recovered | 0:unused; 1:Steam_JSON_plus_one_final_character |
| N2ToggleFavorite | `0x18063c750` | recovered | 0:unused; 1:result |
| UserExistsServlet | `0x18063ce30` | recovered | 0:PS4ID_echo; 1:unused; 2:remembered_login_value; 3:isTesting; 4:isBanned; 5:banDate; 6:banDescription |
| N2SpaceLoading | `0x18063c190` | recovered | 0:SessionGUID; 1:ready; 2:id_space; 3:psidglobal; 4:ip; 5:port |
| N2AddUserOnline | `0x180634750` | recovered | 0:unused; 1:result |
| N2GetPsidglobalAndGuidByUsernamePlatform | `0x180634bb0` | recovered | 0:unused; 1:callback_string1; 2:callback_string2 |
| N2LoadSpace | `0x180635990` | recovered | 0:SessionGUID; 1:isBanned; 2:noFreeSlot |
| N2HousingReadPreset | `0x1806361a0` | recovered | 0:unused; 1:SessionGUID; 2:unused; 3:housingPreset; 4:housing_aux_string |
| N2UserExist | `0x180636a10` | recovered | 0:PS4ID_echo; 1:unused; 2:remembered_login_value; 3:isTesting; 4:isBanned; 5:banDate; 6:banDescription |
| N2UpdateUserOnline | `0x18035a740` | recovered | array ignored |

## Remaining semantics

- This route boundary excludes direct legacy HTTP calls, load balancer and Mirror/TCP application messages.
- Server database, authorization, inventory, housing, scheduling, purchase/order, social, allocation and multi-user behavior remain unproven.
- GetNews consumes count and all remaining string pairs; an arbitrary trailer can cause an exception. Zero-item news conflicts with the shared sender requiring a separator and needs caller-path analysis.
- GetAllInWardrobe discards its final source field and leaves a final null output slot; Send_CheckIsInWardrobeServlet requires an unused fifth field.
- No 1:1 equivalence, launch readiness, or recovered original server source is claimed.

## Exact request field orders

Fields below are joined with `#` before whole-message encryption. No per-field delimiter escaping was observed. JSON companion retains native method addresses, signatures, hashes and pseudocode source paths.

| Route | Request field order |
|---|---|
| N2AddBlock | `PS4Info.SessionGUID#username#platform numeric decimal` |
| N2AddSilenced | `PS4Info.SessionGUID#username#platform numeric decimal` |
| CheckerServlet | `PS4Info.userName#PS4Info.netInfo.ethernetAddress#PS4Info.netInfo.BSSID#Time.get_time().ToString()` |
| Send_CheckIsInWardrobeServlet | `PS4Info.SessionGUID#PS4Info.PS4ID#targetGUID` |
| PlayerPrefsServlet | `PS4Info.SessionGUID#PS4Info.PS4ID` |
| spaceExistServlet | `PS4Info.SessionGUID#PS4Info.PS4ID#PS4Info.spaceParams.ip#PS4Info.spaceParams.port.ToString()#PS4Info.spaceParams.psidglobal` |
| ChannelGUIDServlet | `PS4Info.PS4ID#sha256_ascii_lower_hex(DateTime.Now.ToString())` |
| GetAllInWardrobe | `PS4Info.SessionGUID#id_instance` |
| GetCinemaFilmsServlet | `PS4Info.SessionGUID#PS4Info.PS4ID` |
| GetIinitInfosNeededServlet | `PS4Info.SessionGUID#PS4Info.PS4ID` |
| GetLastUsedPreset | `PS4Info.SessionGUID#PS4Info.PS4ID#targetGuid argument#typeGender numeric decimal (0 MALE, 1 FEMALE)` |
| GetLoadPresetByName | `PS4Info.SessionGUID#PS4Info.PS4ID#guid#typeGender numeric decimal (0 MALE, 1 FEMALE)#presetname` |
| GetNewsServlet | `UnityEngine.Random.Range(0,100).ToString()` |
| PlayerLabelInfoServlet | `PS4Info.SessionGUID#PS4Info.PS4ID#playerGUID` |
| GetPlayerPrefsServlet | `PS4Info.SessionGUID#PS4Info.PS4ID` |
| GetPresetGameServlet | `PS4Info.SessionGUID#PS4Info.PS4ID#guid` |
| GetPurchases | `PS4Info.SessionGUID` |
| N2GetRelationship | `PS4Info.SessionGUID#PS4Info.PS4ID#targetGUID` |
| GetSocialList | `PS4Info.SessionGUID#type.ToString()` |
| N2RemoveBlock | `PS4Info.SessionGUID#username#platform numeric decimal` |
| N2RemoveFriend | `PS4Info.SessionGUID#username#platform numeric decimal` |
| N2RemoveSilenced | `PS4Info.SessionGUID#username#platform numeric decimal` |
| ResetDefaultPresetServlet | `PS4Info.SessionGUID#PS4Info.PS4ID#namePreset#typeGender numeric decimal (0 MALE, 1 FEMALE)` |
| SavePlayerPref | `PS4Info.SessionGUID#PlayerPrefsKeys.ToString() enum NAME#value argument` |
| InfoServlet | `PS4Info.SessionGUID#PS4Info.PS4ID#PS4Info.netInfo.BSSID#PS4Info.netInfo.defaultRoute#PS4Info.netInfo.ethernetAddress#PS4Info.netInfo.httpProxyPort#PS4Info.netInfo.httpProxyServer#PS4Info.netInfo.internalIpAddress#PS4Info.netInfo.mappedIpAddress#PS4Info.netInfo.primaryDNS#PS4Info.netInfo.secondaryDNS` |
| CheckServerStatusServlet | `PS4Info.userName#Time.get_time().ToString()` |
| SetUserInWardrobe | `PS4Info.SessionGUID#ManagerInstance.id_instance#isInWardrobe numeric 0/1#gender enum NAME MALE/FEMALE#userName#userStatus#moodName#nickColor.x.ToString(InvariantCulture)#nickColor.y.ToString(InvariantCulture)#nickColor.z.ToString(InvariantCulture)#ManagerInstance.Memory.LocalPlayer.NebulaPlayer.transform.position.x.ToString(InvariantCulture)#ManagerInstance.Memory.LocalPlayer.NebulaPlayer.transform.position.y.ToString(InvariantCulture)#ManagerInstance.Memory.LocalPlayer.NebulaPlayer.transform.position.z.ToString(InvariantCulture)` |
| STMBuyCrystals | `PS4Info.SessionGUID#steamId#mappedProductId.ToString()#PS4Info.steamManager.STNCountry` |
| STMCompleteOrder | `PS4Info.SessionGUID#steamId#orderId.ToString()` |
| STMCompleteSucceededOrders | `PS4Info.SessionGUID#steamId` |
| STMGetUserInfo | `PS4Info.SessionGUID#steamId argument` |
| N2ToggleFavorite | `PS4Info.SessionGUID#username#platform numeric decimal` |
| UserExistsServlet | `PS4Info.userName#PS4Info.versionGame#PS4Info.isDev Boolean True/False#PS4Info.sAccountId#Time.get_time().ToString()` |
| N2SpaceLoading | `PS4Info.SessionGUID#PS4Info.PS4ID` |
| N2AddUserOnline | `PS4Info.SessionGUID#PS4Info.PS4ID#PS4Info.netInfo.mappedIpAddress` |
| N2GetPsidglobalAndGuidByUsernamePlatform | `PS4Info.SessionGUID#username#platform numeric decimal` |
| N2LoadSpace | `PS4Info.SessionGUID#PS4Info.PS4ID#psidglobal argument#PS4Info.isTesting Boolean True/False#noIdSpace argument#desiredGuid argument` |
| N2HousingReadPreset | `PS4Info.SessionGUID#PS4Info.PS4ID#PS4Info.spaceParams.psidglobal` |
| N2UserExist | `PS4Info.userName#PS4Info.versionGame#PS4Info.isDev Boolean True/False#PS4Info.sAccountId#Time.get_time().ToString()` |
| N2UpdateUserOnline | `PS4Info.SessionGUID#PS4Info.PS4ID` |


`InfoServlet` has eleven fields: SessionGUID, PS4ID, BSSID, defaultRoute, ethernetAddress, httpProxyPort, httpProxyServer, internalIpAddress, mappedIpAddress, primaryDNS, secondaryDNS. The net-info part is delimiter text, not JSON.

`SetUserInWardrobe` sends SessionGUID, instance ID, wardrobe integer, gender, username, status, mood, RGB floats, then XYZ position floats. The six floats use invariant culture. Its instance ID is `ManagerInstance.id_instance`, not PS4ID.

`ResetDefaultPresetServlet` omits the supplied target GUID from its request; that GUID stays in task state for callback handling. `STMBuyCrystals` maps indexes 0..4 to products 1000..5000 and sends country, not currency. The original commerce backend semantics are unavailable.

## Steam identity and exact session hash

`PS4Info.<Init>d__82.MoveNext` at `0x18042AA90` passes out `sAccountId` (+0x28) and `userName` (+0xE0) to `SteamManager.Init` at `0x1804CA510`. Init fills account ID from SteamID's decimal string, fills username from the persona name, and assigns `PS4ID=sAccountId`. The STMGetUserInfo callback only fills currency and country. Therefore the Steam `N2UserExist` response field 0 must echo request field 3 (account ID), not request field 0 (persona name).

The existing-account closure at `0x180642530` writes response field 2 into both `MANAGERLogin.User` and `Passwd`. This is client behavior; the unavailable backend's original meaning and validation for that value remain unknown.

`CRYPTManager.SHA.GetHashSha256` at `0x1805E58B0` uses `Encoding.ASCII` and per-byte `{0:x2}`, producing lowercase hexadecimal. For `ChannelGUIDServlet`, let request fields be `PS4ID#H`. The exact session value is `SHA256_ASCII(PS4ID+"#"+H).lowercase_hex[:32]`. The server receives H and need not reproduce the client's culture-dependent DateTime formatting.

Evidence is static native pseudocode in the cited method files, corroborated with Capstone instructions for ASCII encoding, hex format and identity writes. No networking, game launch, or server launch was performed.

Preset request gender uses decimal integer 0/1: GetLastUsedPreset calls Int32.ToString at 0x18060FBF0, GetLoadPresetByName at 0x1806214E3. Response field2 separately uses MALE/FEMALE names.

SetUserInWardrobe field2 is decimal integer 0/1 (Int32.ToString at0x18063B4E9); field3 is the MALE/FEMALE enum name passed as string by ManagerInstance.OpenCharacterEditor. These two fields use different conversions. Native declarations show isDev/isTesting are bool, while platform and list type are int.
