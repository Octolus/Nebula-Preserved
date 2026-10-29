> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Independent notification text patch review

No concrete native ABI, field-layout, relocation or PE preservation defect was found in the reviewed bytes. The candidate rebuilds in memory exactly to prepared SHA256 `13158d2f08c9511c9cc283a6dda680081c5e1f6142bb86ddde1bfbd039de7fcb`. This is static review, not runtime clearance: no native code, game, UI, listener, connection or synthetic instruction model was executed by this reviewer, and no candidate copy was written or installed.

## Original call site and data layout

The original DLL contains `mov rdi,rcx` at0x47748a. Capstone register-write analysis finds no further RDI write through the final call0x477a02; intermediate calls must preserve RDI under the original Win64 ABI. The rapid+wardrobe input's entire reviewed setter byte range is identical to the original DLL. RDI therefore still holds ChatEntry at the redirect.

Immediately before the original call,0x4779e9 loads the final format into RCX,0x4779f0 copies body RSI to R9,0x4779f3 copies the colored-name RAX to R8,0x4779f6 writes zero to caller RSP+0x20, and0x4779ff copies timestamp R15 to RDX. The E8 at0x477a02 targets String.Format0x13685a0. IL2CPP declarations confirm its four managed parameters plus MethodInfo fifth argument. String.Concat0x1365160 has three managed string parameters plus MethodInfo in R9.

The nullable field starts at ChatEntry+0x108. The native setter's concrete copy establishes HasValue+0x108, NotificationData.type+0x110 and arguments+0x130; the generic Nullable declaration alone would not prove aligned payload offsets. NotificationData's own type+0/arguments+0x20 and String._stringLength+0x10 agree with the dumped declarations. There are no newly authored managed-reference field stores.

## Wrapper ABI, literals and GC exposure

The144-byte wrapper saves RBX,RSI,RDI,R12,R13 (40 bytes) and allocates0x30 (48 bytes). At entry RSP mod16=8; subtracting88 yields an aligned call site. It reserves32 bytes of shadow space and puts Format's null MethodInfo at caller RSP+0x20, which is callee-entry RSP+0x28 after the return-address push. Concat receives null MethodInfo in R9. RBP,R14,R15 and XMM6..15 are untouched. Every saved register and stack allocation is restored in the normal epilogue.

The code calls only the original Concat and Format helpers. RIP-relative reads resolve to the original initialized literal slots0x24f7d08/0x2515838/0x2530b68. The original setter initializes those slots before reaching this call site. Non-null empty body, non-null ChatEntry, HasValue and type3/4 are checked before substitution. Null/nonempty bodies and other types pass through. Gift arguments can be null because the reused managed Concat accepts null strings. The wrapper still invokes original Format for every branch.

Original format/timestamp/name/body references remain in nonvolatile registers across Concat. Its returned managed string moves directly RAX->R13 before the next allocating helper. That follows the native setter's existing register-held reference pattern and adds no unmanaged heap-reference buffer or intervening allocation. Actual collector root discovery, managed helper exceptions and Unity behavior remain untested; the instruction-model report cannot prove those properties.

## PE layout and unwind

All138030 existing runtime-function rows, including the rapid wrapper, are preserved exactly. A single new row covers0x2ca8000..0x2ca8090 and points to unwind data at0x2ca8090. The11-byte prologue and six unwind entries agree with the actual pushes/allocation. Exception dispatch was not run.

The new .nbn section is read/execute. Every old section header is identical; all old section data is identical except the redirect's four changed rel32 operand bytes in the actual `il2cpp` code section (the E8 opcode stays the same). The rapid section and its call redirect remain unchanged. All loader directories other than the moved exception-directory entry are identical. References use signed rel32/RIP-relative displacement and RVA table entries; no absolute pointer relocation is introduced. Both literal pointers and original loader relocation data remain in the old sections. The rebuilt PE checksum verifies and full bytes match the prepared candidate.

## Tool and report guards

Eight parser-only guard checks reject existing source/object/assembly/patcher/prepared-JSON paths, output under steamapps, a non-json report suffix and destination/report aliasing. Source and object resolve strictly; outputs resolve before protected/existence checks; output opens use exclusive creation. A failed report write after the DLL-copy write may leave an isolated copy without a manifest, but it does not overwrite an input. Concurrent malicious replacement of a parent directory is outside these normal-use guards.

The offline test source is a Python integer instruction model with synthetic managed helper stubs. Its recorded16 cases cover gates, ABI alignment, preservation and alternate bases, but do not call native String methods, collect managed objects, render UI or dispatch Windows exceptions. This reviewer read those tests and the report without rerunning the model.

A wording issue identified during review was corrected before final hashing: `notification-text-compatibility.json` now states that unrelated gameplay/UI behavior is excluded while the intended notification text changes. No unresolved actionable finding remains in this static review.

Source hashes, complete wrapper disassembly, call-site argument instructions, field offsets, preserved section/table details and the exact guard cases are in `notification-text-review.json`. Reproduce with `python outputs/nebula-preservation/tools/notification_text_review.py`; it only rebuilds PE bytes in memory and writes these review reports.
