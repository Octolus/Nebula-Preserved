> Historical research: this file records an earlier investigation, not current feature acceptance. The root [PROGRESS report](../PROGRESS.md) is authoritative. Local evidence and extracted game code are intentionally omitted. See [research index](README.md).

# Cinema bootstrap compatibility

The native client cannot safely consume a syntactically valid empty cinema schedule. This report records an authored local no-films compatibility response; it does not claim recovery of the original cinema catalogue, film names, pricing, or media service.

## Observed bootstrap hang

During the first native UI integration run, the local HTTP bootstrap requests returned HTTP 200. The client remained at `LoadingNews` and Windows reported the process as not responding. The bounded native trace reported:

- preceding bootstrap callbacks returned;
- `HTTPGetCinemaFilms.OnResponse` at RVA `0x6085d0` entered;
- `CinemaFilms.Set` at RVA `0x5568b0` entered and did not leave;
- the queued News `OnResponse` at RVA `0x6217e0` did not enter within the observation window.

This observation identifies the active stall. The trace itself is not retained in this report, so its exact instrumentation and event timestamps remain external runtime evidence.

## Static cause

`HTTPGetCinemaFilms.OnResponse` accepts the five fixed fields, creates non-null film-name and duration lists, consumes any remaining fields as name/duration pairs, and calls `CinemaFilms.Set`.

`CinemaFilms.Set` loops while the film-name list object is non-null. With an empty list, its index repeatedly resets to zero and accumulated time remains zero, so the `> 86399` exit condition is never reached. Therefore:

- five fields are the parser-syntactic minimum;
- five fields are not a termination-safe success response;
- a complete name/duration pair is required even when the local service intentionally offers no films.

## Authored local no-films policy

The termination-safe response is:

[Code/listing block omitted from the public research archive.]

The response has seven fields. `LOCAL_NO_FILMS` is an explicit local sentinel, not a recovered or original film identifier. `84600` is the minimum duration that makes `1800 + duration == 86400` on the first iteration. The strict schedule-add condition is `< 86400`, so no `ScheduleFilm` is created; the accumulated time then satisfies the exit condition and `Set` returns.

The sentinel is consequently never displayed or passed to media playback. A real placeholder film and MP4 are not required. Duration `84599` is unsafe for this policy because it creates a schedule entry at second zero.

## Empty generated schedule consumers

The resulting `lScheduleFilms` object is non-null with `Count == 0`:

- `CinemaTicketOffice.<SetCartelera>.MoveNext` checks `Count` before every item access. It immediately breaks, assigns empty strings to its four text controls, yields, and can repeat without indexing the list.
- `StreamingVideo.Initialize` copies the schedule reference and calls `SetScreen`.
- `StreamingVideo.SetScreen` returns when `Count <= index`, before any item access or media launch.
- `StreamingVideo.LaunchFilm` would build the local path `StreamingAssets/<Platform>/f/<filmName>.mp4`, but it is not reached with the empty generated schedule.
- `ScheduleFilm` construction is skipped entirely. Its constructor only stores film name, start second, and duration.
- The declared `CinemaUI` fields contain canvas, bubble, mesh, input, and state references, but no `CinemaFilms` or schedule-list field.

These checks establish static compatibility for the authored empty generated schedule. They do not establish behavior of an original remote film catalogue.

## Verification state

- Original failing runtime behavior observed: yes.
- Static cause recovered: yes.
- Authored sentinel response derived from native arithmetic: yes.
- Consumer `Count == 0` guards recovered: yes.
- Fix runtime retested: **true**, bounded bootstrap callback trace.

The service change has passed the bounded native callback retest described below. This is a bootstrap compatibility result; broader runtime integration remains in progress.

Machine-readable evidence and hashes are in [cinema-bootstrap-compatibility.json](cinema-bootstrap-compatibility.json).


## Bounded native retest

The private native client was executed with observational entry/return hooks after the HTTP fix. CinemaFilms.Set, Cinema response, News response, PlayerPrefs response and the login-screen coroutine all entered and returned. The trace is source-hashed in the JSON report. This proves the bootstrap hang is cleared; world loading and UI flows are tracked separately in `../runtime-validation.json`.
