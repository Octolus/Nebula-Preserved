# Publication privacy

The exported source tree excludes personal account databases, wallet receipts, test identities/configuration, credentials, private keys/certificates, session exports, process memory, private screenshots, logs, crash dumps, full game files and editor caches. Historical machine-specific launchers and runtime evidence are not exported. The dashboard preview in `docs/images/` uses disposable synthetic data.

Machine-specific names, home/workspace paths, hostnames, Steam account identifiers and actual test-server addresses were removed or replaced with portable paths and placeholders. Loopback, wildcard, synthetic test addresses and documentation-only TEST-NET addresses may remain. The endpoint patcher also requires the original game's public service address constants as exact rewrite targets; those are shipped protocol data, not the preservation operator's addresses.

The destination originally held a single initial commit containing only `.gitattributes`. Its Git metadata was preserved privately outside this directory and the publication repository was initialized fresh with a neutral project identity. It has no remote and no imported author history.

An old provisional release archive was deliberately not copied because technical receipts inside it contain private paths. New release artifacts need a separate content/privacy review after construction. Git ignore rules reduce accidental inclusion; they do not sanitize files you explicitly force-add.

Run `python scripts/audit_public_tree.py` before each publication. It examines tracked and unignored files for sensitive/generated artifacts, account-like Steam identifiers, private workspace paths, common token formats and the current machine's username/hostname. It reports file paths and issue categories without printing matched secrets. Review staged files manually too: automated checks cannot recognize every possible secret or personal detail.
