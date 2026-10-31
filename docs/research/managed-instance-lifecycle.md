> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Managed instance lifecycle v1

Managed lifecycle is an explicit preservation deployment policy. It is disabled by default and does not change manually launched instance behavior.

Enable it only with both HTTP flags:

[Code/listing block omitted from the public research archive.]

The backend never starts a process, allocates a port, or trusts a supervisor journal as readiness evidence. It owns account/apartment bindings, pending demands, capacity reservations and `desired-instances.json`. A separate supervisor owns process and port leases. Clients become ready only through the existing fresh `instances/<instance_id>/instance-status.json`, housing-binding and semantic-interaction gates.

## Native flow

The recovered native pending flow is preserved exactly:

- `N2LoadSpace` accepts a durable demand with `{guid}#false#false`.
- `N2SpaceLoading` returns `{guid}#false` until the exact desired instance is ready.
- Ready returns `{guid}#true#{instance_id}#{psidglobal}#{ip}#{port}`.
- A false poll is repeated by the native client after scaled `WaitForSeconds(1)`, with no observed retry counter.

An accepted pending demand is retained while its session remains current. Each poll renews its short active lease. Stopped polling makes the demand inactive for supervisor drain without deleting its durable target; a later valid poll can renew it. Allocated demands stay active while exact fresh presence exists, with a bounded post-allocation grace before an empty world becomes stopped.

After the last demand or allocation, an empty world stays desired `running` for an
operator idle grace (`NEBULA_PUBLIC_WORLD_IDLE_SECONDS`, default 900, for shared
worlds; `NEBULA_PERSONAL_WORLD_IDLE_SECONDS`/`NEBULA_IDLE_TTL`, default 60, for
apartments), tracked in `managed_instances.last_active_at`. Such rows carry zero
counters, so the supervisor may evict them for queued demand. With
`NEBULA_MAX_PROCESSES` set, `N2LoadSpace` answers its native `noFreeSlot=true`
when the target is not running and every slot holds another live demand or
present player, because `N2SpaceLoading` has no recovered failure terminal.

## Account and apartment policy

Every account, existing and new, owns `Home` plus the operator's starter apartments (`NEBULA_STARTER_APARTMENTS`, default `Home,CliffApartment,LakeApartment`; `Home` is always included). New accounts are provisioned at login (`N2UserExist`, `UserExistsServlet`, `N2AddUser`); existing accounts are backfilled once when the managed backend starts. Each applied starter apartment is recorded in `starter_apartment_grants` (account, apartment, instance, whether the binding was created, `starter_apartments_v1`), so a starter apartment is applied once per account: a shrunken list or a staff removal is never undone, and nothing is removed automatically. `Home` is re-ensured on every login and cannot be removed. An existing valid binding (for example an admin-bound legacy ID) is adopted rather than duplicated. The earlier `managed_account_policy` table (new-accounts-only Home, preexisting accounts grandfathered with nothing) is kept only as a historical record.

Original client evidence (recovered; no game binaries or dumps are in this repository):

- `NavigatorSelector` declares `const string HOME = "Home"`. `SetPersonalSpaces` (RVA `0x47d5b0`, called from the `OnClickAsync` state machine `0x486af0`) activates the `Home` navigator entry unconditionally, deactivates every other personal entry, then re-activates entries whose name equals a `Persistency.purchasedAssets[personalspaces]` (`TypePurchase` 9) name. Those come from GetPurchases (`HTTPGetPurchases.OnResponse` `0x634fb0` → `Persistency.AddPurchasedAssets` `0x615f30`) and are matched on `personalspacesName`.
- The legacy `NETGCloudSpace.GetPersonalSpaces` (`0x3e86a0`) applies the same rule to `GetPersonalSpacesServlet` field 3 split on `!`: `Home` → `SetActive(true)`, others → `false`, then each returned name → `true`. Its sender `Send_GetPersonalSpaces` (`0x3ecc10`) has no direct call site in this build.
- Other apartments were shop products: the shop's gender option 4 is the authored `Spaces` sprite, and `ShopManager.OnPersonalSpaceSelected` (`0x4adc20`) requests `GetItemAssetsData(shopId, gender, "PERSON")` (`0x411490`); `EntryGender.OnClick` (`0x4a86e0`) uses the same `PERSON` literal. Item type 8 is `PersonalSpace` (`CW_Wardrobe.itemType`, `AEManager.TypeItem`). `WardrobeWindow.ShowScrollPersonalSpacesScreenShots` (`0x4b8030`) previews apartment screenshots. `SpaceLoaderPersonalspaceTrigger.OnTriggerEnter` (`0x46c200`) only loads its apartment when `Memory.ContainsPurchasedPersonalspace` (`0x610820`) finds it among purchases. Public "open house" showrooms (`TheNebulianOpenHouse`, `NebuHouseOpenHouse`, `WestValleyApartmentOpenHouse`) are in the navigator.
- `PreInitLOAD.PersonalSpacesDisabled` is empty. `Utils.RewardType` (0–11) has no apartment reward, and no free, promotional or tutorial apartment grant was found.

So only `Home` is recovered as free and default; it needed no server grant in the original. `CliffApartment` (reviewed empty generic baseline, no extra interactions) and `LakeApartment` (verified wall/ceiling slots and floor areas, exercised in managed allocation and all-scene protocol smokes) are a preservation choice, not recovered entitlements. The other 30 navigator apartments are sold again in the shop's Spaces tab under their shipped shop IDs (see [ITEM-METADATA-EVIDENCE.md](../ITEM-METADATA-EVIDENCE.md#apartments-personal-spaces)); their 150 crystal / 75 NP price is preservation policy because original prices were not recovered. A purchase, gift or staff offer grant goes through the same `ApartmentPolicy.bind` as a starter or panel grant, and `GetPurchases` then lists the apartment's shop ID with its navigator name.

Staff can give or remove an apartment in the panel's Character → Apartments tab (`POST users/<id>/character/housing/grant|remove`, `players.data` permission, idempotent and audited; no reason required). Removal needs a confirmation click, refuses `Home`, an open two-part save, or an apartment someone is in or entering, and deletes its binding and saved layout (the layout is kept in the audit `before` record). Its `managed_instances` row stays, so a later grant reuses the same stable instance ID.

New personal instance IDs are `apt-` plus a random UUID4 hex value. New public pool IDs are `pub-` plus UUID4 hex. IDs never encode an account name or identifier. Existing valid admin bindings are adopted without renaming. The unique owner/logical-space database constraint and `BEGIN IMMEDIATE` make concurrent first requests converge on one binding.

A visitor invite is pinned during `N2LoadSpace` to the exact desired owner session and bound apartment. Before allocation, that owner session must still be current, freshly present and allocated to the same instance. A visitor is never redirected to another apartment or a newer owner session.

## Capacity

Public selection uses the greater of descriptor player count and exact fresh allocated presence, plus pending/not-yet-present reservations. The total must remain below the descriptor's native maximum of 32 before accepting another reservation. This closes concurrent HTTP over-allocation while descriptor files lag.

## Backend-owned desired snapshot

Path: `<state-dir>/desired-instances.json`

Top-level exact fields:

- `format_version`: integer `1`
- `generation`: finite Unix time
- `managed`: Boolean `true`
- `instances`: rows sorted by `instance_id`

Each row has:

- `instance_id`: safe opaque string
- `kind`: `public` or `personal`
- `psidglobal`: exact admitted scene
- `owner_ps4_id`: personal owner, or empty for public
- `logical_space_key`: personal navigator key, or empty for public
- `desired_state`: `running` or `stopped`
- `active_demands`: unexpired current-session pending and allocated demands
- `pending_reservations`: pending plus allocated clients not yet present
- `active_allocations`: fresh present clients whose database allocation exactly matches
- `adopted_existing`: Boolean indicating a preexisting safe identifier
- `readiness_profile`: exact `nonmini-semantic-v1`

`stopped` rows are retained so the supervisor can drain an owned child and preserve stable IDs. `instance-housing.json` remains the only personal ownership registry.

## Supervisor-owned runtime journal

The coordinated path is `<state-dir>/managed-instance-runtime.json`. It may record the desired generation, leased port/token, PID and process start token, argument/build hashes, health times, restart/backoff state and counters. The backend deliberately never reads this file when deciding readiness.

The supervisor may launch only the pinned Linux build with backend-authored identity and these arguments:

[Code/listing block omitted from the public research archive.]

`build-linux-validation.json` executable, managed assembly and source hashes are the launch pin. The supervisor must not kill or relabel a process it cannot prove it owns.

## Safety boundary

- Client scene, owner and instance fields never become command arguments directly.
- Supervisor output cannot grant ownership or readiness.
- Personal binding, descriptor owner, scene, semantic epoch and endpoint must all match current backend snapshots.
- Manual mode creates no managed schema intent, desired snapshot, default or starter apartment or pending behavior. Staff grants there only create the binding.
- Full server/game readiness remains separately tracked; this lifecycle only orchestrates already reviewed instance profiles.
