> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Rapid-boat release compatibility candidate

Authored same-build rapid-boat compatibility candidate. Static PE checks and synthetic instruction-model tests only.

The native rapid-boat exit sends no release packet. The prepared client copy adds a guarded release through the original sender, and the replacement instance refreshes remote viewers because the shipped release receiver cannot do that itself. This is authored compatibility behavior, not original server parity.

The candidate includes the separately reviewed wardrobe loop fix. It is a private copy under `work/patched-client-rapid`; the installed Steam binary is unchanged. Candidate SHA256: `ce1a74588e74499e282699e160b966439ffb4c278e8bcef791951e28a57b0dd0`.

Static checks cover PE layout, call relocations, instruction boundaries, stack alignment, unwind metadata and preservation of existing data. A synthetic instruction model passes 30 cases using stubbed native functions; it executes no original game code. Independent review reproduced both supported input variants and found no high-confidence ABI or PE defect. Review did identify an output-path issue, now covered by rejection checks.

The new wrapper is486 bytes. The patch changes34 bytes within the old file and adds one RX section containing the wrapper and extended unwind table. It preserves all138029 original runtime-function records. The original exit is called exactly once; only a successful local index0 exit can send `31#GUID#False#0`.

Remaining limits: Windows loader/unwinder and live IL2CPP garbage collector have not exercised the wrapper. Additional helper calls can throw before the original caller continuation; native unwind metadata propagates rather than swallows exceptions. Two-frame remote teardown/reseed sequencing, animation state and transform races require future runtime validation. This is a new preservation compatibility policy, not a recovered original server operation.

Full evidence and hashes: [report](rapid-boat-compatibility.json), [prepared-copy manifest](README.md#omitted-local-evidence), [synthetic checks](README.md#omitted-local-evidence), [instance reconstruction](README.md#omitted-local-evidence).
