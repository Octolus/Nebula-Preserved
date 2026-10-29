> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# HTTP social contracts

Static reconstruction for Steam build 11018722. Four social handlers bring the backend to 51 routes. Native pseudocode is not original C# source. No game, server, listener or connection test was run; networking parity remains unproven.

| Route | Request before global platform trailer | Response |
|---|---|---|
| N2GetSocialList | GUID#PS4ID#listTypeInt#selectorInt | unused#unused#selectorInt#countInt#EntryData entries |
| GetSocialList | GUID#typeInt | unused#JSON with lUsernames string list |
| N2GetPsidglobalAndGuidByUsernamePlatform | GUID#username#platformInt | unused#psidglobal#GUID |
| N2GetRelationship | GUID#PS4ID#targetGUID | Exactly five fields; relationship integer at index 4 |

AES.Encrypt at RVA 0x6A32C0 appends the platform enum name inside encryption for every caller, including direct legacy coroutines. Removing the trailer based on a caller's plaintext builder would be incorrect. Server replies omit it.

## Legacy social entries

N2GetSocialList is a special case in generic OnSend at 0x414E40: it bypasses the usual true/session/PS4ID response checks. Its consumer at 0x3E8C40 reads selector at index 2, count at 3, and exactly count serialized entries from 4. Selector 0 feeds wardrobe/shop gifting UI; selector 1 feeds social UI. Empty is `true#GUID#selector#0`, with no arbitrary trailer.

SocialListEntryModel public fields are, in order: bool isFavourite; Status status; string name; Int32 platform; ListType listType. Private EntryData.textIndex is excluded by public Type.GetFields. Each value is prefixed by one UTF16 code unit equal to 0x24 plus its UTF16 length. Primitive/enum lexical strings follow immediately, without a separator. The independent golden example is `)False+Offline)Other%1+Friends`. Supplementary Unicode characters count as two UTF16 units.

Status values are Online 0, Away 1, Offline 2, Wardrobe 3. ListType values are Friends 0, Silenced 1, Blocked 2, SpaceUsers 3, PSN 4. EntryData emits enum names; native Enum.Parse also accepts numeric tokens. The implemented legacy menu types are the caller-proven 0/1/2; other selections return 501.

Modern GetSocialList has a different request and JSON response. Its public DTO is `{lUsernames: List<string>}`. The type parameter is Int32; no direct call to its Process was found in the verified game-code range 0x352000..0x900000. Treating 0/1/2 as ListType is an explicit local interpretation, not proof of original server selection semantics.

## Join lookup and relationship flags

Invite acceptance callback at 0x488FE0 proves lookup response index 1 is psidglobal and 2 is GUID. An empty psidglobal selects the cannot-connect branch; `OK##` is the local offline response. A positive lookup requires unique exact username/platform, fresh instance presence and a matching ready allocation. Duplicate local username/platform identities return 409 instead of selecting an arbitrary account.

N2GetRelationship requires exactly five response fields. Code 1 sets isFriend; 2 isFavorite; 3 isSilenced; 4 isSilencer; 5 isBlocked; 6 isBlocker. Block branches deactivate the remote player object. The replacement resolves overlaps as own block 5, reverse block 6, own silence 3, reverse silence 4, favorite 2, friend 1, none 0. This precedence is local policy, coordinated with the instance social layer.

## Durable instance handoff

The account snapshot retains its version 1 schema and adds `companion_ids` and `locomotion_ids` string arrays containing only explicit catalog-validated resource grants. Empty arrays grant nothing; older account readers may ignore the extra fields. Companion/locomotion HTTP lists, GetPurchases parallel ID/name lists and the instance snapshot use the same resource entitlement helper.

An additional atomic `instance-relations.json` has version 1, generation Unix seconds, and relations containing ps4_id, exact target username, canonical target_platform (PS4/StandaloneWindows), and kind (friend/favorite/block/silenced). Existing numeric platform rows migrate without losing relations. The two output files share generation and use separate atomic renames; no cross-file transaction is claimed.

Mirror writes `instance-presence.json` containing generation and bound player GUID/status pairs. Only a supported snapshot aged 0..15 seconds establishes Online/Away/Wardrobe; missing, invalid or stale data yields Offline. The HTTP reader accepts UTF8 with an optional BOM.

Friend approval uses immutable atomic `friend-events/<UUID>.json` files with version 1, operation accept_friendship/remove_friendship, actor_ps4_id, other_ps4_id, created_at and policy correlated_online_request_v1. The instance producer correlates the request and recipient approval before emitting an event. Lowercase UUID N and D spellings are accepted and normalized to D for SQLite receipts; the filename must match the supplied spelling. UTF8 with an optional BOM is accepted.

HTTP imports events before handlers: both directional friend rows and an idempotence receipt commit in one SQLite transaction. Timestamp ordering prevents an older delayed approval resurrecting a removed friendship; removal wins exact timestamp ties. Invalid or unknown-account events remain unacknowledged. HTTP removals also record chronology. No HTTP AddFriend endpoint was invented.

Original persistence, authorization, external PSN behavior, list ordering and blocked/friend overlap policy remain unknown. The JSON includes bounded method hashes and explicit replacement policies. No live cross-process file handoff was tested.

## Validation

All 26 offline backend tests pass, including 19 contract/state checks and 7 resource module checks. Every test patches socket.socket to raise. Added cases cover independent EntryData golden strings, Unicode UTF16 length, distinct modern/legacy framing, reciprocal persistence, UUID/BOM compatibility, canonical snapshots, late/repeated events, stale presence, exact lookup result order, platform ambiguity and shared explicit resource grants. No networking readiness is claimed.
