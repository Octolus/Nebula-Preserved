# Licensing and distribution scope

Original Nebula Preserved contributions are licensed under the root
[MIT license](../LICENSE). This covers the project's original reconstruction
code, tools, tests and documentation, only to the extent the contributors have
authority to license them.

The root license does not relicense vendored components, upstream adaptations,
dependency packages, Unity software or the original game's content. See
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for the component boundaries
and retained notices.

## Original game and research inputs

The repository contains a reconstruction server and tools for an independently
supplied game installation. It does not include a license to Nebula Realms game
binaries, models, textures, audio or asset bundles. Protocol identifiers, schemas
and research references do not establish ownership of the original material.
Client patches and delta packages require a separate contents and distribution
review; their reproducible generation is not permission to redistribute the
original client. Where provenance or redistribution rights for a proposed
addition are unclear, resolve that item before including it. Do not label
third-party or recovered material as original MIT-licensed code.

## Source and binary releases

Unity editor/build modules and compiled engine runtime remain subject to their
applicable terms. A source release and a compiled Unity server image have different
contents. Before publishing a runtime image or client bundle, review its actual
included files and redistribution requirements, including native libraries and
the build toolchain's runtime components.

The checked-in workflows currently produce build provenance, but do not generate
a resolved dependency SBOM or license inventory. Maintainers must supply and review
those reports before distributing runtime images or client bundles.

For each release, retain the exact dependency lockfiles, generate a dependency
SBOM and license inventory in CI, and include the notice texts required by the
resolved versions and distributed artifacts. Review unknown license results and
dependency changes before publishing. An automated inventory is evidence of
contents; it does not replace the applicable license texts or grant additional
rights.

Contributions should be original work or carry a compatible upstream license and
documented provenance. Do not strip copyright headers or replace a dependency's
license with the root project license. Licensing questions and unresolved
distribution boundaries should be settled before a release is published.
