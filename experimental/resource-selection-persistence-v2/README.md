# Durable selected resources — historical overlay

The primary backend and scene-server source now include the reviewed resource-selection integration and current-session guards. This directory preserves the earlier overlay and its original tests for research. Its merge recipe pins an older baseline: do not reapply it to the integrated primary tree. See [source layout](../../docs/SOURCE-LAYOUT.md) and [current progress](../../docs/PROGRESS.md) for current source and native acceptance status.

Historically, this overlay passed independent review, 13 temporary-database tests and full C# assembly compilation before primary integration. The matching later integration also passed a complete private Unity Linux/Weaver build. Fresh native client selection, rejection, peer replication and restoration acceptance remains incomplete.

The backend remains the only SQLite writer. Per-instance immutable request/ack files bind each selection to the exact latest session, allocated scene, fresh process-owner lease, canonical entitlement and expected per-account/kind revision. Selection and replay receipt commit in one transaction; the scene broadcasts only after a matching durable ack and account-snapshot revision. Empty selection removes the resource. Revocation clears the selection and later grants do not silently restore it.

The additive tables are `resource_selections(ps4_id,kind,item_id,revision,updated_at)` and `resource_selection_receipts(request_id,digest,response_json,processed_at)`. They do not modify wallets, presets, profiles or ownership. No public HTTP endpoint or Unity SQLite connection is added. The operator-controlled local state-directory trust boundary matches existing scene IPC.

The historical overlay tests can still be run from the repository root:

```sh
python experimental/resource-selection-persistence-v2/test_resource_selection.py
```

Tests use temporary databases only. They normally import the historical overlay module; the packaging authority check separately imported the integrated primary `backend/resource_selection.py` before loading this suite. The preserved `merge.py` verifies the older `base-pins.json` and writes a NEW `generated/` overlay; it refuses existing output and never edits primary sources. It is retained as history and is not an update command for the integrated tree. Build the complete current Unity scene server and generate a new source/artifact report before runtime use. Do not hot-replace a DLL under an old report.

Bounds: one pending request per peer,15-second lifetime,128 queued requests per instance,512 processed per backend scan and4096-byte request/ack limit. Acks publish after commit. Durable receipts prevent repeat application; abandoned IPC files expire after an additional30 seconds. Retain receipts while any old requests could be replayed. Paths reject links; service-account filesystem permissions remain required.

Unexpected catalog errors preserve existing selection state. Invalid/revoked catalog entries clear it before export. On original-client rejection or success, typed TCP15/17 responses reconcile the sender from its bound authoritative snapshot, without creating a new wheel request. The original processors call the same companion/locomotion update chain used for remote players. The reviewed bodies show local remove/instantiate and companion Persistency updates; downstream initialization and actual local-avatar timing still need native acceptance.

A timeout or failed ack publication does not prove the database was unchanged: the commit may already have succeeded. Recovery reuses the immutable receipt without a second mutation. Remaining tests include same-sender rejected selection recovery, peer visual replication, removal and fresh-process/session/scene restoration, including wheel/menu state. No runtime proof is inferred from temporary DB tests or static compilation.
