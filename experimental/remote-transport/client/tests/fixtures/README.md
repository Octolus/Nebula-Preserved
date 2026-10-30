# Synthetic public certificates

These four DER certificates are authored TLS verification fixtures, not deployment
trust material. Their only names are `play.example.org` and documentation address
`203.0.113.10`. Certificates are valid from 2026-01-01 through 2030-01-01. Tests use
an explicit fixed verification time, so they do not depend on the host clock.

The CA, unrelated CA, DNS/IP leaf and DNS-only leaf were signed with temporary
in-memory RSA keys. No private key is included or retained. Tests exercise normal
rustls verification for a valid chain, wrong name, missing IP SAN, expiry,
not-yet-valid, unrelated root and damaged signature. These checks do not establish
native client or production endpoint acceptance.
