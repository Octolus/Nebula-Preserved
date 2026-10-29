# Experimental public-access v9 overlay

This directory preserves the reviewed, undeployed public-access v9 source
overlay. It is intentionally separate from the repository's primary backend,
mirror, protocol, and tools baseline.

## Compatibility boundary

The merge receipt binds this overlay to exact historical base hashes. The
primary preservation tree may now contain newer resource-selection and other
authoritative backend work. Do not copy these files over the primary tree and
do not treat a clean textual merge as proof of semantic compatibility.

The operational delta recorded by the merge receipt is:

- `backend/economy_admin.py`
- `backend/housing.py`
- `backend/public_access.py`
- `backend/public_access_admin.py`
- `backend/server.py`
- `backend/service.py`
- `backend/state.py`
- `tools/backup_state.py`
- `tools/migrate_public_access.py`

Client authentication and remote bootstrap source is under `client/`. The
reviewed binaries are identified by digest in `evidence/`; compiled binaries are
not included here.

## Reproduction, not activation

Only against the exact base hashes in
`evidence/PUBLIC-ACCESS-MERGE-RECEIPT.json`, the merge can be reproduced with:

```text
python experimental/public-access-v9/tools/merge_public_access.py --help
python -m py_compile experimental/public-access-v9/backend/*.py
```

The first command prints usage only. Do not run a merge against the current
primary tree without a new three-way review, migration review, full offline
validation, and runtime acceptance.

The templates in `config/` require HTTPS and an authorization credential. That
credential authenticates a preservation account; it is not a Valve/Steam
ticket and this overlay does not implement Steam-ticket validation. The raw
Mirror/Telepathy gameplay transport still must remain private/VPN unless the
separate remote-transport experiment is composed and accepted.

No service was installed or started while curating this overlay. Public
activation remains false.
