> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Parameterized shared-endpoint metadata copy

This patch prepares a private IL2CPP29 `global-metadata.dat` copy for a chosen
HTTP API origin and advertised IPv4 address. It does not modify the Steam
installation, launch the game, start a listener, or prove runtime connectivity.

## Parameters

`make_endpoint_metadata_copy.py` accepts:

- `--api-origin`: canonical `htt[local-path]` with an optional port. Credentials,
  hostnames, HTTPS, paths, query strings, fragments, IPv6, whitespace, and
  noncanonical IPv4 spellings are rejected.
- `--advertise-ip`: one canonical IPv4 address with no port or other syntax.

The exact defaults remain `htt[local-path]` and `127.0.0.1`. For backward
compatibility, that default path retains the previously reviewed byte output
SHA-256 exactly:
`76e10da141d2daacd99c0976f362ddbf9463321aeef69ea464230565202885fd`.

## IL2CPP29 rewrite

The metadata header stores the string-literal record table as a byte offset and
byte count, followed by the string-literal data offset and byte count. Each
eight-byte literal record is `(length, index)`, with `index` relative to the
selected literal-data blob.

Custom endpoints may be longer than an original literal. They are never
truncated. The tool:

1. Hash-guards the exact analyzed metadata source.
2. Parses all 12,850 literal records and validates every range.
3. Rejects any selected range that overlaps an unselected literal.
4. Appends a complete copy of the original literal-data blob.
5. Appends each full replacement value to that new blob.
6. Changes only the four selected `(length, index)` records.
7. Updates only the header literal-data offset and byte count.
8. Re-parses the result and verifies every unselected record, index, length,
   and decoded value remains unchanged.

All other original sections stay at their original offsets. The old literal
data remains untouched in the original file prefix; the header points readers
to the appended complete blob.

## Prepared example

The isolated prepared copy uses documentation-only example address
`203.0.113.10`:

[Code/listing block omitted from the public research archive.]

- Prepared copy SHA-256:
  `08e1d5d33f89ea41c887dc183664597f33d853b5424efd5301fa1c30c8cebc10`
- Layout: `appended_full_literal_data_blob`
- Installed original: unchanged.
- Runtime execution/connectivity proof: none.

The prepared manifest records every selected record and both old/new offsets:
[`prepared-shared-endpoint-copy.json`](README.md#omitted-local-evidence).

## Boundary

Only four exact compiled literals are changed: two HTTP base literals and two
load-balancer address literals. Dynamic destinations, hosts returned by the
backend, asset/config origins, Steam SDK traffic, and other compiled endpoints
remain outside this patch. Static parser validity is necessary but does not
prove the game will accept or use the copy at runtime.
