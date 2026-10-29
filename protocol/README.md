# Runtime schemas and catalogs

These JSON files contain source-derived protocol schemas, canonical item IDs, asset-path metadata and authored compatibility policy used by the backend. They contain no game asset bundles, textures, meshes, executable or account database. The client must supply its own installed content.

The export includes the inputs referenced by backend code and portable tests: avatar schemas/defaults/catalogs, neutral avatars, resource entitlements, apartment/placement metadata, interaction manifests, notification contracts and removal sentinels. Original authoring-machine absolute paths have been normalized; old research citations may refer to extraction evidence that is deliberately not redistributed. Such citations are historical provenance, not executable filesystem dependencies.

`core-test-readiness.json` describes integration profiles, not a certificate that every feature works. Catalog rows establish shipped identifiers and categories; operator-authored store offers/prices remain distinct. Neutral avatar JSON is a reconstructed default, not a private player's saved preset. New schemas or catalogs must be reviewed alongside the backend and scene server that consume them.
