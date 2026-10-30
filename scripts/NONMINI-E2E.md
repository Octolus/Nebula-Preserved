# Backend process acceptance

Run this separately from the fast offline unit suite:

```bash
python3 -B scripts/nonmini_backend_e2e.py --artifacts /private/NEW-acceptance-run
```

Use the same Python dependencies as the backend. The output directory must be
new and outside the checkout. The command owns two loopback HTTP listeners,
creates two fictitious credential-bound accounts in a disposable database, and
stops its child process before returning. It never connects to a deployed server,
reads a personal account, changes the Steam installation, or controls the desktop.
Host proxy settings and HTTP redirects are disabled for this harness.

The checks cover real encrypted game HTTP and the management API, including:

- Bootstrap, anonymous denial and cross-account denial.
- Credit adjustments, idempotent receipts, conflicting retries and moderator
  economy denial.
- Server-priced purchases, tampered-price denial and eight concurrent purchase
  requests producing exactly one debit/grant.
- Serialized male character/outfit save and preference save.
- Reciprocal friendship projection after a trusted event handoff fixture.
- Owner/visitor apartment allocation, visitor edit denial, atomic 101-item
  two-part save, unpublished partial saves, duplicate acknowledgement and visitor
  read.
- Fresh backend processes and fresh login sessions restoring the outfit/body,
  settings, wallet, purchases, friendships and complete apartment layout.
- Historical-session write denial, kick/replay, persistent ban and fresh login
  after unban.

`result.json` reports named checks, duration, pass/failure, explicit scope and
source hashes. **The artifact directory also contains a generated management
token, disposable account database and request log. Keep the whole directory
private; do not upload it as a public CI artifact.** Only the summary is suitable
for a separately reviewed publication.

Scene status/presence metadata and the correlated friendship event are explicit
fixtures. No real scene listener is represented by those files. This checks the
backend's HTTP, authority and persistence boundary; it does not establish native
game acceptance, Mirror/chat transport, TLS ingress, complete historical server
parity, or minigame behavior. Process restart is controlled, not a power-loss test.
