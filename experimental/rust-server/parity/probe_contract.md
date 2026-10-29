# Private parity probe, version 1

This is a synthetic, headless comparison with the authored preservation reference. It is not an original-server or original-client certificate.

Run the candidate as a long-lived process. stdin and stdout contain UTF-8 JSONL only. Write diagnostics to stderr. Preserve `id` exactly and reply once per request. Every operation may return `{ "id": "...", "ok": false, "error": "NOT_IMPLEMENTED" }`; this is `NOT_PROVEN`, never a pass. A crash or timeout also cannot prove a contract.

* `init`: `{id,op:"init",state_dir,reference_protocol_dir,core_test_profile:null}`. Open a fresh disposable state directory supplied by the harness. No real credentials, external state, listeners, assets, network or account lookup. Reply `{id,ok:true}`. Reject a second init. `reference_protocol_dir` contains schemas/catalog metadata, not game assets.
* `http`: `{id,op:"http",route,method:"GET",plaintext}`. `plaintext` is the complete client request including its final platform trailer. Encrypt it with the client codec and pass through the server HTTP adapter. Alternatively `data` supplies raw query ciphertext; absence of both means a missing query. `headers` is an optional object. Return `{id,ok:true,status,body,plaintext,content_type}`: `body` is the exact HTTP response text, `plaintext` the decrypted response or JSON null when decryption fails, `content_type` excludes charset. Treat method case exactly. Do not silently repair, trim, strip, reorder or canonicalize request/reply fields.
* `snapshot`: `{id,op:"snapshot"}`. Return `{id,ok:true,state:{tables:{TABLE:{columns:[{name,type}],rows:[{COLUMN:VALUE}]}}}}`. Include all non-`sqlite_` durable SQLite tables, even empty ones; columns are in declared order, declared `type` uppercase. Values preserve null, integer, real and text. BLOB values use `{blob_hex:"lowercasehex"}`. Row order is ignored by the driver, value types and all other values are exact. A non-SQLite implementation may expose an equivalent projection but must not fabricate reference rows. Partial state must return `NOT_IMPLEMENTED`, not a partial successful snapshot.
* `restart`: `{id,op:"restart"}`. Close all backend state handles, then reopen the *same* disposable state directory. Return `{id,ok:true}`. This exercises store reopen in one probe process; full process-crash durability remains a separate gap.
* `close`: `{id,op:"close"}`. Close owned handles, return `{id,ok:true}`, then terminate successfully.

The driver also has a `process_restart` corpus operation. This is not sent to a probe: the driver closes the old probe, starts a new process with the same command, and calls `init` with the same disposable state directory. `init` must preserve existing valid disposable state on reopen. It remains the first operation in the new process. This proves graceful process reopen only, not abrupt-crash recovery.

## Audited configured fixture extension

`init` optionally includes `fixture`, an object read verbatim from the hash-pinned `fixtures/configured-mutations-v1.json`. The exact schema and table/column allowlist are `fixtures/schema.json`; the reference seeder is `fixture_support.py`. No arbitrary SQL, code, filesystem operation, listener, credential, secret table or external account is accepted. Two explicitly named synthetic accounts are provisioned through the login/session handlers, then the whitelisted configuration rows are inserted with parameterized statements into a fresh disposable database. Reopen requests omit the fixture and preserve state.

The separate configured corpus exercises real mutations against that configuration. It pre-stages one original housing counterpart so the serial JSONL request can commit through the real HTTP adapter; full concurrent part1-before-part0 waiting remains unproven. Exact notice dedupe rows are pre-staged to exercise existing-notice idempotence while avoiding UUID normalization; new notification creation remains unproven. A deliberately invalid second bundle child is fault data for atomic rollback, not a supported grant.

Configured state uses its separate explicit fourteen-field clock whitelist. HTTP/UUID values remain exact. In addition to cross-implementation comparisons, every declared no-change boundary compares each probe's raw snapshots exactly, including timestamps; normalization cannot hide an idempotence or rollback write.

The driver compares HTTP status, exact raw reply, exact decrypted reply and content type. Only the explicit whitelist in `normalization.json` may change compared fields. Currently no HTTP normalization exists. Typed durable timestamps use the narrow table/column whitelist with numeric/nonzero validation; zero and null are preserved. No UUIDs, item identifiers, session IDs, balances, schema columns, list order, JSON field order or status codes are normalized.

Mirror messages, application transitions, concurrency, fresh/concurrent housing staging, public credential authentication, world authority and TLS are inventoried but not exercised by this adapter. Their status remains `NOT_PROVEN`.

## Synthetic management extension

After ordinary `init`, send `{id,op:"admin_init",token,operators}`. The token and operator list must come from reviewed `admin/fixture.json`, pinned by `admin/registry.json`; this is fixed synthetic public test data. Reply `{id,ok:true}`. Management tables are initialized once; reopening with the same configuration preserves disabled operators and audit history.

Send `{id,op:"admin",method,tail,headers,body,query}`. `tail` is relative to `/management/v1/`, `headers` is a string object, `body` is a structured JSON value, and `query` is an optional URL-encoded string without `?`. POST corpus requests explicitly include `Content-Type: application/json`. Reply `{id,ok:true,status,body}` where `body` is the structured response object. Error responses retain their exact status, code and message. This extension does not expose arbitrary SQL, file access, real credentials or listeners.

The management comparator preserves scalar types and array order, while JSON object key order is insignificant. Its separate source-bound `admin/coverage-manifest.json` permits only explicit clock paths and correlated request/news UUIDs. Replay identity, UUID syntax and cross-table identity remain checked. News date labels must match their creation clock, maintenance duration remains exact, and durable audit/receipt JSON must be canonical before normalization. Raw no-change comparisons preserve every field. These rules do not modify the default or configured game HTTP comparisons.
