> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Notification text compatibility candidate

## Result

A separate build-11018722 `GameAssembly.dll` candidate now restores the missing
body text for offline Gift (`type == 3`) and system Reward (`type == 4`)
notifications.  It is layered on the already prepared rapid+wardrobe copy and
does not modify the original installation or either input DLL.

Candidate SHA-256:
`13158d2f08c9511c9cc283a6dda680081c5e1f6142bb86ddde1bfbd039de7fcb`.

## Static evidence

`ChatEntry.set_notification` at RVA `0x477470` copies the nullable notification
to `ChatEntry+0x108`.  The recovered declaration gives this layout:

- `ChatEntry+0x108`: `Nullable<T>.HasValue`
- `ChatEntry+0x110`: `NotificationData.type`
- `ChatEntry+0x118`: `NotificationData.playerName`
- `ChatEntry+0x130`: `NotificationData.arguments`

The native pseudocode shows that Gift builds
`" has sent you " + arguments + " as a gift"` and Reward selects
`"System Reward"` only after `GetguidByUsername` returns a nonempty result.
That lookup enumerates the remote-player dictionary, so offline donors and the
actual self/system reward can reach the final formatter with an empty body.

Capstone decoding of the exact input bytes around the final call establishes
the local ABI at RVA `0x477A02`:

[Code/listing block omitted from the public research archive.]

`RDI` is a Win64 nonvolatile register and remains the `ChatEntry` at the
redirect.  The authored wrapper preserves all five nonvolatile registers it
uses and has matching generated unwind metadata.

## Bounded behavior

The redirect replaces only the five-byte call at RVA `0x477A02`.  The wrapper:

1. passes through immediately unless the body is a non-null managed string of
   length zero, the nullable has a value, and the type is Gift or Reward;
2. for Gift, calls the original three-string concat helper with the original
   prefix/suffix literal slots and `ChatEntry+0x130` arguments;
3. for Reward, uses the original Reward literal slot;
4. calls the original four-argument `String.Format` helper for every path.

Nonempty bodies and every other notification type are unchanged.  The patch
does not alter remote-player lookup, identity checks, purchases, rewards,
acceptance handlers, unrelated UI behavior, listeners, attachment behavior, or security
checks.  It adds no imported function or writable-and-executable section.

## Offline verification

- Strict source hash: the input must be the reviewed rapid+wardrobe private
  copy (`ce1a7458...57b0dd0`).
- The `.nbp` rapid section and all 138,030 existing runtime-function records
  are preserved; one new `.nbn` RX section and one runtime-function record are
  appended.
- Capstone decodes all 144 authored code bytes, every local branch lands on an
  instruction boundary inside the wrapper, and all five relocations are pinned
  to reviewed same-build RVAs.
- Generated unwind data describes the five pushes and 48-byte allocation.
- A pure Python decoded-instruction model passes 16 cases across image bases
  zero and `0x180000000`, with helper stubs, volatile-register poisoning,
  stack/alignment checks, and nonvolatile-register preservation.
- Negative path guards reject existing, input-equal, and `steamapps` output
  paths before writing.

## Limits

No game, Unity process, original native function, UI, listener, socket, or
attachment was started.  Runtime text rendering, IL2CPP GC interaction, and
Windows exception dispatch/unwinding have not been tested.  This is an exact
build candidate, not evidence of original-server parity or runtime success.

