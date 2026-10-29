# Publishing source

Publish a reviewed source snapshot with the [MIT license](../LICENSE) for original
contributions and all [upstream notices](../THIRD_PARTY_NOTICES.md). Source
publication does not establish original-client acceptance or permission to
distribute the game. See [licensing scope](LICENSING.md) and the separate
[image and client-bundle gates](RELEASES.md).

1. Read [progress](PROGRESS.md), [privacy](PRIVACY.md) and [security](../SECURITY.md).
   Keep the development label and current acceptance limits visible. Review
   game-derived manifests and any proposed delta payloads individually.
2. In this repository, run `python scripts/audit_public_tree.py` and the relevant
   [component checks](TESTING.md). Inspect their results. The hygiene audit checks
   Git-visible files; it does not replace review of contents, dependency terms
   or release archives.
3. Review `git status --short` and `git ls-files --others --exclude-standard`.
   A fresh checkout assembled without commits contains untracked source that
   `git diff` will not show. Keep generated runtimes, databases, credentials,
   private captures, decompiler output and complete game files outside the
   source publication. Local `work/`, `releases/` and build output are ignored.
4. After the intended changes are reviewed, run
   `python scripts/update_source_inventory.py --write`, then
   `python scripts/update_source_inventory.py --check`. This refreshes publication
   hashes without changing historical runtime evidence. Avoid concurrent edits
   while refreshing the inventory.
5. Stage only the reviewed source paths. Inspect `git diff --cached --stat`,
   `git diff --cached --check` and `git diff --cached`, including binary files
   and notices. Re-run the hygiene and inventory checks against the final tree.
   Check the author identity before creating the commit; it becomes public
   commit metadata. The inventory excludes itself by design.
   The initial snapshot retains byte-pinned upstream files, Unity serialization
   and multiline SQL strings. Review their existing whitespace warnings without
   bulk-formatting those inputs or invalidating their evidence hashes.
6. Choose the intended repository/remote and review workflow triggers,
   permissions and generated artifact contents before publishing. A push to
   `main` can trigger the configured container publication workflow when its
   prerequisites are present. Publish only the reviewed commit and intended
   artifacts; keep operator secrets in the configured secret store.

These instructions do not configure a remote, change repository settings or
publish anything automatically. Runtime builds and client bundles need their
own contents, dependency-notice and acceptance review even when source checks pass.
