> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Native settings UI compatibility

The native Options surface has a working persistence path for ordinary audio, camera, chat, profanity, and name/status/mood visibility controls. Music is runtime-proven end to end at `0.9`: Windows UI save and panel reopen passed, and a later fresh Linux-backed login restored the value.

The bounded audit found three optional-control gaps:

- Notification-login enum 19 updates the native field but does not issue `HTTPSavePlayerPref` from the recovered toggle/setter path.
- The shipped `ShowPets` toggle is serialized as enum 19 instead of enum 20, so it targets notification state; native toggle dispatch has no enum-20 case.
- PlatformOnly enum 21 saves, but the replacement `GetPlayerPrefs` response and recovered native hydration do not restore it on login.

These are not current blockers for the normal non-minigame flows. The precise source map, evidence hashes, and five-step follow-up are in [`work/native-settings-ui-audit.md`](README.md#omitted-local-evidence). Only Music has live runtime coverage; all other control outcomes remain static or proposed tests.
