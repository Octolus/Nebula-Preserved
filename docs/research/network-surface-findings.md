> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Network surface coverage audit

The existing 40 HTTP task routes and 45 targeted legacy routes cover 73 distinct names. This audit confirms **48 additional compiled route names**, giving a minimum of **121** across these bounded audits. This count describes compiled client routes, not implemented backend routes or original server parity.

No game/server was launched and no network connection test was made. The inventory is derived from source-hashed metadata, native artifacts and bounded direct-call decoding.

The census found 69 application UnityWebRequest caller bodies, 3 WWW/content caller bodies, 2 local DNS caller bodies and 1 video URL caller body. SDK API presence alone is not evidence of application runtime use.

## Additional surfaces

| Surface | Concrete observation | Review status |
|---|---|---|
| Modern HTTP task queue | 40 native route identifiers; envelope/task response contracts are separate files. | existing bounded audit; HTTP task count is not all HTTP |
| Login/Editor/Space direct HTTP | 45 route names in targeted legacy audit; overlaps modern tasks. | existing bounded audit |
| Additional generic cloud HTTP | Housing, shop/purchase/gift/crystals, full-game lobby/statistics/invites, gathering/events, archery/boat scoring, XP and maintenance clients. Native bodies encrypt request strings, URI-escape them, build GET ?data= URLs and consume AES response envelopes. | transport bodies and concrete listed route arguments observed; per-route DTOs/field order/state effects remain separate unreviewed contracts |
| Dedicated full-game/space-liveness HTTP | AddToPoolFullGameServlet, CheckIsAvailableToJoinFullGameServlet and CheckIfSpaceStillExistServlet use dedicated coroutines rather than the generic HTTP sender. | concrete HTTP routes observed; pool/join/liveness rules and all payload fields not reconstructed by this audit |
| Shop image URL fetches | UIShopItemEntry.loadImage and wwwLoadImage construct Unity WWW from caller-provided URL; loadImage consumes downloaded texture. | dynamic fetch surface observed; URL origins, schemes, catalog links and cache policy not fully traced |
| Asset bundle URL/cache fetches | AssetBundleManager.LoadAssetBundleInternal concatenates static BaseDownloadingURL with assetBundleName; manifest uses new WWW, regular bundle uses WWW.LoadFromCacheOrDownload with manifest hash and CRC0. Existing/in-flight bundles are deduplicated. | compiled fetch surface observed; actual configured URLs, local-vs-remote schemes and scene/bundle reachability are unproved |
| Cinema movie path | StreamingVideo.LaunchFilm concatenates Application.streamingAssetsPath + "/" + Platform.ToString() + "/f/" + filmName + ".mp4", assigns the result to one VideoPlayer and copies that URL to a second. Two verified direct set_url calls occur at RVAs0x55fd92/0x55fe34. The three path literals resolve at0x24e58e8,0x24e7c78,0x24e54a8. | native local StreamingAssets movie path established for this body; VideoPlayer API use here does not establish a remote movie service |
| Loadbalancer configuration and dynamic space hosts | loadbalancerConn getters return production104.196.60.146, development104.196.161.5 and port28000. PS4Info.Init assigns production getter result to field+0xf0. Space/host destinations may also arrive dynamically in backend responses. | constants and one native assignment observed; not proof of every active socket destination or restored loadbalancer policy |
| Local network-info DNS | PCNetInfoGetter.GetInternalIpAddress checks network availability, calls DNS.GetHostName and DNS.GetHostEntry for that local hostname, then selects an address. Process also has verified raw direct DNS calls, but its current Ghidra body removes blocks as possible PIC construction. | local-host address discovery observed; do not treat these calls as evidence of another cloud endpoint |
| Mirror TCP/game replication and transport libraries | 80 registered application TCP opcode handlers are covered by existing TCP/minigame audits; Mirror spawn/authority/SyncVar/command state and transport calls are additional layers. Telepathy/KCP/SimpleWeb code is compiled. | application opcode field recovery does not establish whole Mirror stream or server state parity |
| Steam networking/auth SDK wrappers | 85 Steam networking wrapper RVAs and6 selected ticket/auth wrapper RVAs found in metadata. This bounded E8 scan found no direct application calls to those selected wrappers. | SDK presence established; runtime use, inlined/PInvoke/indirect paths and Steam DLL internals remain outside this census |

## Additional concrete routes

All names below have literal route arguments passed to a confirmed generic HTTP sender, or a dedicated coroutine that consumes the URL template. Their full payload/state contracts remain unreviewed in this inventory.

`HousingNETGcloud`: `GetHousingTypeServlet`, `HousingReadPresetServlet`, `HousingSavePresetServletParts`.

`NETGcloudNPGather`: `Get_BRAINMEMORION`, `Get_GatherChristmasGetSpacesCompleted`, `Get_GatherConsume`, `Get_GatherConsumeReward`, `Get_GatherPhaseGame`, `Get_GatherStatus`, `Get_npGather`, `Get_npGatherChristmas`, `Get_npGatherProcessItem`, `Send_GatherInitInSpace`.

`ShopNETGcloud`: `GetFeaturesServlet`, `GetGenderDataShopServlet`, `GetItemAssetsDataServlet`, `GetShopDataShopServlet`, `GetShopInfoPlayerShop`, `GetShopTypeDataShopServlet`, `NPShopBundleItemsServlet`, `NPShopBuyItemServlet`, `NPShopGiftItemServlet`, `NPShopIsItemPurchasedServlet`, `NPShopSyncCrystalsServlet`.

`PS4Info`: `checkerToServerDownMaintenanceServlet`.

`BlueWaveHideoutNETGCloud`: `AddScoreBoatMiniGameServlet`, `GetBestScoreBoatMiniGameServlet`, `GetLeaderboardBoatMiniGameServlet`.

`CastleNETGCloud`: `AddScoreArcheryServlet`, `GetBestScoreArcheryServlet`, `GetLeaderboardArcheryServlet`.

`FullGameNETGCloud`: `AddStatisticsServlet`, `CreateGameServlet`, `GetActiveStagesServlet`, `GetFullGameLeaderboardServlet`, `GetInviteFriendList`, `GetLastScoreServlet`, `GetOpenGamesServlet`.

`ArcheryCupidManager`: `Get_GatherArcheryCupid`, `Send_ArcheryCupidConsume`.

`FootRaceManager`: `GetCooldownServlet`, `SetCooldownServlet`.

`GatherMedievalVillage`: `Get_GatherMedievalVillage`, `Send_GatherMedievalVillageConsume`.

`GatherUIMemorionGame`: `MemorionServlet`.

- `AddToPoolFullGameServlet` (dedicated HTTP coroutine).
- `CheckIfSpaceStillExistServlet` (dedicated HTTP coroutine).
- `CheckIsAvailableToJoinFullGameServlet` (dedicated HTTP coroutine).

## Remaining review boundaries

- Additional routes listed here require their own request/response field, EntryData/JSON, success/error and side-effect contracts; observed generic AES framing does not supply their application semantics.
- Any bodies in missing_application_caller_pseudocode require native reads; compiled direct callsites already establish those API paths but not their complete payload or URL construction. The legacy avatar coroutine0x3b0040 reached a bounded30-second Ghidra decompile timeout; do not treat its missing pseudocode as absence of HTTP behavior.
- Asset bundle base URL setters, caller-provided image URLs, serialized asset/config URLs, dynamically returned server/space addresses and cinema/media URLs are not exhaustively traced.
- The raw direct-call census omits indirect virtual/interface/function-pointer calls, import calls and native UnityPlayer/Steam library internals. A zero direct call count cannot prove an API is unused.
- Several Ghidra constructor/Process bodies remove blocks after possible-PIC warnings. Endpoint literals referenced there do not prove URL branch selection; raw instruction review is needed before adopting constructor control flow.
- Original authentication/ownership binding, persistence, recipient policies, pricing/purchases, event progression, minigame adjudication and authoritative Mirror state are not recoverable merely by counting client handlers.

There are 1 verified application caller bodies still missing pseudocode in this snapshot. Their exact RVAs/names, every direct callsite, endpoint and route literal reference, and artifact hashes are in the JSON files.

Framework XML namespace URLs and SDK strings are retained as candidates, not classified as game backend endpoints. HTTP base literals include production App Engine and localhost; Ghidra constructor warnings prevent assuming every URL selection branch from pseudocode alone.
