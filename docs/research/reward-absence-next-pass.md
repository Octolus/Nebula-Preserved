> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Reward absence next pass

This bounded review covers the two `CheckOwnGenericReward` 404 responses observed during the Linux native Nexus run, followed by the authored suppression implementation and offline checks. Later controlled HTTP adapter checks and current Linux unit checks are recorded in the separate [postvalidation source delta](README.md#omitted-local-evidence); no new native reward-UI run is claimed.

## Conclusion

`owned=false` is **not** the native “no reward” response. Field 3 false calls `GenericOneAssetRewardTrigger.Show`, makes the trigger actionable, and allows a local-player collision to send `GenericReward`. Returning false for an unconfigured key would advertise a reward that the backend correctly refuses to grant.

The observed 404 was an intentional fail-closed local boundary. It granted nothing and wrote no claim marker, but it was not a clean recovered wire response: the HTTP adapter returned plaintext error text while this consumer expects an encrypted response with at least four `#` fields.

Field 3 true is the only recovered success branch that cleanly keeps the trigger hidden. Using it for a missing or disabled definition would mean “treat unavailable as already owned.” That can be an explicit preservation compatibility policy, but it is not recovered original-server semantics.

The explicit preservation policy is now implemented:

- Do not replace 404 with `owned=false`.
- A missing or disabled definition returns the normal `false#GUID#PS4ID#true` response from `CheckOwnGenericReward` only.
- The suppression check performs no database write, entitlement grant, claim marker, or debit.
- `GenericReward` remains fail-closed with 404 for the same key.
- To restore the actual reward interactions, configure validated local grants for both shipped keys; original item choice, eligibility, schedule, and migration rules remain unknown.

## Exact native transition

`GenericOneAssetRewardTrigger.Start` at `0x465a60` first deactivates `gArt`, then starts the ownership check for its serialized `idasset`.

The check consumer at `0x3f7540` decrypts and splits the response, requires at least four fields, and parses only field 3:

- `true`: dispose and return; the art remains hidden and `isActive` remains false.
- `false`: call `Show` at `0x465a10`.

`Show` sets `isActive=true`, activates the trigger GameObject, and activates `gArt`. `OnTriggerEnter` at `0x465690` sends `GenericReward` only when `isActive` is true and the collider is the local player. The grant consumer at `0x3f9530` calls `ShowReward` only when its field 3 is true; `ShowReward` at `0x465870` loads the `idasset_Thumbnail` sprite and displays the reward UI.

## The two Nexus triggers

Both triggers are active and enabled in `s/nexuslogicprefab` (`7a555fddd0bf0743444f60a3eacf0533cc6ce3a546995b6bd6ffc2ed10bd5f66`):

| Object | idasset | Component path ID | Raw SHA-256 |
|---|---|---:|---|
| `GenericOneAssetRewardTrigger` | `MYOfHwFv5yhf2L8ph1X5x15ixTJ63Tq3` | -4914210199622857319 | `e0230ea1bf7f6558006cd6f9d84cf56929f77a9ef8946dedc964b0c3860202ba` |
| `GenericOneAssetRewardTrigger (1)` | `DIB25J6p06KJcVg1raYAeRqo75I8cTgy` | 1619769086334488248 | `7babc406ce2ebca35eac619cf10d4bed9c98f904c32ba4723fa08686ec6058cf` |

Their serialized `Regalo` art objects are active, but `Start` forcibly hides them before the request. This explains why the failed checks do not create an actionable trigger.

## Implementation and tests

`RewardService.dispatch` now reads the `GenericReward` definition for the ownership check. Missing or disabled definitions return field 3 true immediately without a write. Enabled definitions continue to report only the durable claim marker. `GenericReward` still uses `_claim` and `_required` before any grant or claim write, so an absent or disabled claim attempt is denied.

The HTTP adapter returns `ProtocolError` text unencrypted with the error status. That is safe for authorization but not the success framing consumed by `0x3f7540`.

Ten focused reward tests pass offline with socket construction forbidden, and the complete backend suite passes all 124 tests. The focused checks prove the configured lifecycle plus exact missing/disabled suppression framing, zero DB writes during the checks, no claims or entitlements, explicit claim denial, and later enablement remaining eligible for one real claim. No live service or native client was reloaded; that controlled observation remains parent-owned.

## Core status

This is not a blocker for the scoped Nexus core. The Linux run completed its login, allocation, world, avatar, Mirror, and chat checks despite both historical 404s. The two Nexus reward interactions remain unavailable until an administrator supplies grant definitions, but their missing-policy checks now use valid silent-suppression framing.

Machine-readable evidence and exact source hashes are in [reward-absence-next-pass.json](reward-absence-next-pass.json).
