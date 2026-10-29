# Preservation HTTP backend

The supported hosting path is [Linux Docker Compose](../deployment/docker/README.md), including managed Unity instances and the [Astro administration panel](../admin-panel/README.md). The commands below are development and maintenance tools. The backend now integrates public-access authentication, the internal management API and atomic two-part apartment saves; historical experimental overlays must not be applied again.

Python3.10+ and the packages in `requirements.txt` are required. Run commands from the repository root. The backend resolves `protocol/` relative to its source, so no original investigation directory is needed.

```sh
python -m venv .venv
# Activate the environment using your shell's usual command.
python -m pip install -r backend/requirements.txt
python -m unittest discover -s backend/tests -q
```

The tests use synthetic accounts and temporary databases. Private extracted-asset provenance tests are explicitly skipped because those inputs are not redistributed. A passing suite verifies reconstructed contracts and persistence, not complete original-server parity.

To start a private local HTTP endpoint deliberately:

```sh
python backend/server.py --listen --bind 127.0.0.1 --advertise-ip 127.0.0.1 --port 8080 --state-dir ./private-state --core-test-profile nonmini-semantic-v1 --managed-instances
```

This command is an operational example and was not run while packaging. Without `--listen`, no listener starts. Use the same concrete private advertised address for the scene supervisor and patched clients. `--local-test-identities` is optional, admits only synthetic fixed test identities and requires a concrete private bind/advertise address. It is unnecessary for ordinary accounts.

The backend owns SQLite and publishes same-host JSON snapshots for scene processes. Managed instances also require a separately built Unity scene server and the hash-verified `tools/instance_supervisor.py`; HTTP alone cannot load a world. Consult `mirror-server/README.md` for build requirements. Keep state outside version control and back up the database consistently before migrations or administration.

First login creates neutral avatars and their initial wardrobe. Fresh accounts do not automatically own apartments, and a fresh database does not contain a complete store catalog. The explicit `admin.py`, `housing_admin.py`, `resource_admin.py`, `shop_admin.py` and other admin modules operate only when invoked. Read their `--help` before using them. `tools/seed_local_shops.py` defaults to a plan; applying its small authored catalog requires an explicit state directory. Its prices are local preservation policy, not recovered publisher prices.

For an explicit operator-created account, replace the uppercase placeholders with the account identifier used by that player's client and the intended display name; no real account is supplied here:

```sh
python backend/admin.py --state-dir ./private-state account ACCOUNT_ID --name PLAYER_NAME
python backend/shop_admin.py --state-dir ./private-state wallet-show ACCOUNT_ID
python backend/resource_admin.py --help
python backend/housing_admin.py --help
```

The primary `shop_admin.py wallet` command sets an explicit balance; it is not an additive credit operation. The panel's additive wallet adjustments are authenticated, idempotent and audited. Public-account credential administration is provided by `public_access_admin.py`; its separate operator key is not the dashboard password or management service token. Do not run migrations or admin writes against an active database without a consistent backup and a reviewed operating procedure.

The primary source now includes durable companion/locomotion selections and current-session ownership guards. SQLite remains the backend's responsibility: scene processes request a selection through bounded same-host IPC, and broadcast only after a matching committed acknowledgement and account snapshot. The integrated source passed the staged backend suite and 13 resource-selection authority tests; original-client selection/rejection reconciliation, peer appearance and fresh-process restoration still need native acceptance with a matching rebuilt scene server. The older `experimental/resource-selection-persistence-v2` overlay is retained as history and must not be reapplied to this integrated tree. Public credentials, TLS gateway and internal management are integrated, but the repaired public client still requires original-game acceptance. Keep management port 8090 internal; the panel is its authenticated browser-facing interface. See [current progress](../docs/PROGRESS.md) for observed native behavior and unresolved flows.
