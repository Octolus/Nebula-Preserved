# Legacy PublicAccess source

These six source files are retained unchanged because the historical optional/test pipeline locks their exact hashes. They are not the current public networking default. The legacy consumer requires managed request-header and redirect methods absent from the shipped stripped Unity metadata, so its configured public HTTPS mode is unsupported.

Build the repaired current consumer from `../network-only/public-access/` instead, following that README and `../network-only/network-profile-contract.json`. It uses the exact owned loopback sidecar, whose upstream HTTPS enforces account Authorization, CA/hostname verification and no redirects. The strict client builder accepts only the reviewed matching new wrapper digest. A legacy DLL cannot pass that check.

Keep this legacy source lock and optional builder semantics unchanged. Do not combine their historical wrapper or GameAssembly/helper pins with a current networking-only release plan. Current public native TLS acceptance remains pending.
