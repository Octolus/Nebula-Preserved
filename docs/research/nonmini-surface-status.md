> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Non-minigame HTTP surface status

Static classification of concrete compiled HTTP route names against Service.ROUTES; no runtime, listener or connection.

The bounded union contains **121** concrete compiled route names. The replacement service declares **92**. Of the **29** outside it, **26** are deferred game routes, **0** belong to non-minigame feature expansions, **3** are retired Steam commerce operations, and **0** are unimplemented operational routes.

## Core loading/account conclusion

Within the recovered route families used for login/account creation, avatar presets and entitlements, world allocation and wardrobe, social/reporting, housing and consumables, there is **no missing route declaration**. This is a bounded static result, not a runtime success claim. `CheckIfSpaceStillExistServlet` is separately compiled under `MITM_Space`; it has not been shown to run on the selected modern HTTP-allocation → local bundle → direct Mirror path.

## Expanded non-minigame features

### cinema social interaction

implemented local preservation policy.

- `CinemaInteractionNPServlet` — `NETGCloudSpace$$Send_CinemaInteractionNP` at 0x3ea1a0

### gathering and event progress

implemented local preservation policy.

- `Get_GatherConsume` — `NETGcloudNPGather$$Send_GatherConsume` at 0x3f2e90
- `Get_GatherConsumeReward` — `NETGcloudNPGather$$Send_GatherConsumeReward` at 0x3f2590
- `Get_GatherMedievalVillage` — `GatherMedievalVillage$$CheckIsAvailable` at 0x690700
- `Get_GatherPhaseGame` — `NETGcloudNPGather$$Get_GatherPhaseGame` at 0x3f0130
- `Get_GatherStatus` — `NETGcloudNPGather$$Send_GatherStatus` at 0x3f4b30
- `Get_npGather` — `NETGcloudNPGather$$Send_Init` at 0x3f4e70
- `Get_npGatherChristmas` — `NETGcloudNPGather$$Send_GatherChristmas` at 0x3f2190
- `Get_npGatherProcessItem` — `NETGcloudNPGather$$ProcessItem` at 0x3f18d0
- `Send_GatherInitInSpace` — `NETGcloudNPGather$$Send_GatherInitInSpace` at 0x3f4730
- `Send_GatherMedievalVillageConsume` — `GatherMedievalVillage$$SendConsumeMedievalVillageItem` at 0x691120

### generic rewards and promotions

implemented local preservation policy.

- `CheckOwnGenericReward` — `NETGCloudSpace.<Send_CheckOwnGenericRewardCoroutine>d__16$$MoveNext` at 0x3f7540
- `GenericReward` — `NETGCloudSpace.<Send_GenericRewardCoroutine>d__18$$MoveNext` at 0x3f9530
- `RewardClothServlet` — `NETGCloudSpace.<Send_rewardBeachTShirtCoroutine>d__14$$MoveNext` at 0x3ffd70
- `RewardConsumeServlet` — `NETGCloudSpace$$Send_RewardConsume` at 0x3ed990
- `SKLPromoServlet` — `NETGCloudSpace$$Send_SKLPromoConsume` at 0x3ee1d0
- `SKLPromoTriggerServlet` — `NETGCloudSpace$$Send_SKLPromoCheckToSetAvailable` at 0x3ede80
- `checkRewardAvailableServlet` — `NETGCloudSpace.<checkRewardAvailableCoroutine>d__35$$MoveNext` at 0x4161b0

### separate space liveness

implemented local preservation policy.

- `CheckIfSpaceStillExistServlet` — `dedicated coroutine` at 0x46e360

### shop catalog and local transactions

implemented local preservation policy.

- `GetFeaturesServlet` — `ShopNETGcloud$$Send_GetFeatures` at 0x410f60
- `GetGenderDataShopServlet` — `ShopNETGcloud$$Send_GetGenderData` at 0x411100
- `GetItemAssetsDataServlet` — `ShopNETGcloud$$Send_GetItemAssetsData` at 0x411490
- `GetShopDataShopServlet` — `ShopNETGcloud$$Send_GetShopData` at 0x411950
- `GetShopInfoPlayerShop` — `ShopNETGcloud$$Send_ShopInfoPlayer` at 0x413cb0
- `GetShopTypeDataShopServlet` — `ShopNETGcloud$$Send_GetShopTypeData` at 0x411e50
- `NPShopBundleItemsServlet` — `ShopNETGcloud$$Send_NPShopBundleItems` at 0x412710
- `NPShopBuyItemServlet` — `ShopNETGcloud$$Send_NPShopBuyItem` at 0x412a60
- `NPShopGiftItemServlet` — `ShopNETGcloud$$Send_NPShopGiftItem` at 0x412fe0
- `NPShopIsItemPurchasedServlet` — `ShopNETGcloud$$Send_NPShopIsItemPurchased` at 0x4134a0
- `NPShopSyncCrystalsServlet` — `ShopNETGcloud$$Send_NPShopSyncCrystals` at 0x413830

Shop/gift, ordinary gathering, promotions, generic rewards, cinema and space liveness now have authored handlers. Shop offers, balances, reward definitions and event configuration require explicit local administration. Debit/grants/claim markers use atomic SQLite groups. Native field acceptance does not establish retired catalog data, scheduling or original rules.

See [shop](http-shop.md), [rewards/cinema/liveness](http-rewards.md) and [gathering](http-gathering.md). Handler presence is not an end-to-end compatibility result; unknown original policy and branch-specific response meanings remain explicit in those contracts.

## Deferred and deliberately disconnected

Deferred game/full-game routes: `AddScoreArcheryServlet`, `AddScoreBoatMiniGameServlet`, `AddStatisticsServlet`, `AddToPoolFullGameServlet`, `CheckIsAvailableToJoinFullGameServlet`, `CreateGameServlet`, `GetActiveStagesServlet`, `GetBestScoreArcheryServlet`, `GetBestScoreBoatMiniGameServlet`, `GetCooldownServlet`, `GetFullGameLeaderboardServlet`, `GetInviteFriendList`, `GetLastScoreServlet`, `GetLeaderboardArcheryServlet`, `GetLeaderboardBoatMiniGameServlet`, `GetLeaderboardServlet`, `GetOpenGamesServlet`, `Get_BRAINMEMORION`, `Get_GatherArcheryCupid`, `Get_GatherChristmasGetSpacesCompleted`, `MemorionServlet`, `Send_ArcheryCupidConsume`, `SetCooldownServlet`, `SetLeaderboardServlet`, `XSpacesGamesType0Servlet`, `checkRewardGameServlet`.

External commerce routes remain disconnected: `STMBuyCrystals`, `STMCompleteOrder`, `STMCompleteSucceededOrders`. Offline administration is the preservation entitlement path; the implementation must not claim a Steam purchase succeeded.

`checkerToServerDownMaintenanceServlet` is implemented with an explicit local no-maintenance status. The native consumer accepts zero without displaying an announcement; original service operations policy is unavailable. See [maintenance evidence](http-maintenance.json).

## Evidence boundary

Every listed additional route has a concrete static caller or targeted legacy contract in the machine-readable report. A compiled caller proves code presence, not reachability. Direct-call scans exclude indirect calls, dynamically built routes and code outside the inspected binary. The 121 count is therefore a minimum concrete union, not a complete live trace.

See [machine-readable status](nonmini-surface-status.json), [surface inventory](README.md#omitted-local-evidence), [surface findings](network-surface-findings.json), and [legacy contracts](http-legacy-contracts.json).
