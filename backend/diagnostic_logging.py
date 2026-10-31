"""Bounded JSON-line output and privacy-safe HTTP diagnostic metadata."""
import contextvars
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import sys
import time
import traceback

MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 5
MAX_RECORD_BYTES = 64 * 1024


class _SafeRotatingHandler(RotatingFileHandler):
    last_failure = float("-inf")

    def handleError(self, record):
        # logging's default handler prints the exception and original record.
        now = time.monotonic()
        if now - self.last_failure >= 60:
            self.last_failure = now
            sys.stderr.write('{"event":"request_log_write_failed"}\n')


class RotatingJSONLog:
    """write/flush/close adapter; one bounded JSON record per write call."""
    def __init__(self, path, *, max_bytes=MAX_LOG_BYTES, backup_count=LOG_BACKUPS, transient=False):
        if type(max_bytes) is not int or not MAX_RECORD_BYTES <= max_bytes <= MAX_LOG_BYTES:
            raise ValueError("Invalid log size limit")
        if type(backup_count) is not int or not 1 <= backup_count <= LOG_BACKUPS:
            raise ValueError("Invalid log backup limit")
        self.handler = _SafeRotatingHandler(path, mode="a", maxBytes=max_bytes,
                                            backupCount=backup_count, encoding="utf-8",
                                            delay=transient)
        self.transient = transient
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.closed = False

    def write(self, text):
        if self.closed:
            raise ValueError("I/O operation on closed log")
        original_length = len(text)
        if len(text.encode("utf-8")) >= min(MAX_RECORD_BYTES, self.handler.maxBytes) or "\n" in text.rstrip("\n"):
            text = '{"event":"request_log_record_rejected","reason":"record_limit"}'
        self.handler.handle(logging.LogRecord("nebula.requests", logging.INFO, "", 0,
                                             text.rstrip("\n"), (), None))
        if self.transient:
            # Rare diagnostic records: hold no descriptor between writes; reopened on demand.
            self.handler.close()
        return original_length

    def flush(self):
        self.handler.flush()

    def close(self):
        if not self.closed:
            self.handler.close()
            self.closed = True


def route_label(command):
    """A bounded route token; query strings/headers are never supplied here."""
    return command if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,95}", command) else "invalid_route"


def safe_stack(error):
    """Bounded code locations, without exception text, paths, locals or source."""
    frames = []
    trace = error.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        filename = Path(code.co_filename).name
        function = code.co_name
        frames.append({"file": filename if re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", filename) else "unknown",
                       "function": function if re.fullmatch(r"[A-Za-z0-9_<>]{1,96}", function) else "unknown",
                       "line": trace.tb_lineno})
        frames = frames[-8:]
        trace = trace.tb_next
    return frames


WARNING_WINDOW = 60.0
MAX_THROTTLE_KEYS = 4096
STATUS_REASONS = {400: "invalid_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
                  405: "method_not_allowed", 409: "conflict", 429: "rate_limited", 500: "server_error",
                  501: "not_implemented", 503: "unavailable"}
_request = contextvars.ContextVar("nebula_diagnostic_request", default=None)


def account_ref(account):
    """Pseudonymous correlation value; identical to the gateway actor_ref."""
    return hashlib.sha256(account.encode("utf-8")).hexdigest()[:16]


def safe_id(value):
    value = str(value)
    return value if re.fullmatch(r"[A-Za-z0-9_.:@+-]{1,96}", value) else "invalid_id"


class Throttle:
    """At most one record per key per window; later records carry the suppressed count."""
    def __init__(self, window=WARNING_WINDOW, max_keys=MAX_THROTTLE_KEYS, clock=time.monotonic):
        self.window, self.max_keys, self.clock, self.entries = window, max_keys, clock, {}

    def check(self, key):
        now = self.clock()
        entry = self.entries.get(key)
        if entry and now - entry[0] < self.window:
            entry[1] += 1
            return None
        if entry is None and len(self.entries) >= self.max_keys:
            self.entries = {k: v for k, v in self.entries.items() if now - v[0] < self.window}
            if len(self.entries) >= self.max_keys:
                return None
        self.entries[key] = [now, 0]
        return entry[1] if entry else 0


THROTTLE = Throttle()
_file_sink = None


def configure_file_sink(path):
    """Mirror diagnostic JSON lines to a size-rotated file that survives container recreation."""
    global _file_sink
    previous, _file_sink = _file_sink, None
    if previous is not None:
        previous.close()
    if path is None:
        return None
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        _file_sink = RotatingJSONLog(path, transient=True)
    except (OSError, ValueError):
        sys.stderr.write('{"event":"diagnostic_file_unavailable"}\n')
    return _file_sink


def write_line(line, file_only=False):
    if not file_only:
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
    if _file_sink is not None:
        try:
            _file_sink.write(line)
        except (OSError, ValueError):
            pass


def emit(event, throttle_key=None, **fields):
    """One compact JSON line on stdout, the stream Docker retains with rotation."""
    if throttle_key is not None:
        suppressed = THROTTLE.check((event, *throttle_key))
        if suppressed is None:
            return False
        if suppressed:
            fields["suppressed"] = suppressed
    record = {"event": event, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              **{key: value for key, value in fields.items() if value is not None}}
    write_line(json.dumps(record, separators=(",", ":"), ensure_ascii=True))
    return True


def begin_request(request_id, route):
    return _request.set({"request_id": request_id, "route": route, "actor_ref": None, "reason": None})


def end_request(token):
    _request.reset(token)


def current_request():
    return _request.get()


def missing_data(reason, **ids):
    """Warn that a lookup the client depends on was empty; only inside a game request."""
    context = _request.get()
    if context is None:
        return
    context["reason"] = reason
    emit("missing_data", (context["actor_ref"], reason, *sorted(ids.items())), level="warning",
         reason=reason, route=context["route"], request_id=context["request_id"],
         actor_ref=context["actor_ref"], **{key: safe_id(value) for key, value in ids.items()})


def failure_reason(status, default=None):
    context = _request.get()
    return (context and context["reason"]) or default or STATUS_REASONS.get(status, "protocol_error")


def report_exception(request_id, route, error):
    """Full traceback to stderr for operators; every line carries the correlation id."""
    prefix = f"[request_id={request_id}] "
    lines = [f"unhandled_exception route={route}\n",
             *traceback.format_exception(type(error), error, error.__traceback__)]
    write_line(json.dumps({"event": "unhandled_exception", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           "request_id": request_id, "route": route, "traceback": "".join(lines[1:])[-16000:]},
                          separators=(",", ":"), ensure_ascii=True), file_only=True)
    try:
        sys.stderr.write("".join(prefix + line for chunk in lines for line in chunk.splitlines(True)))
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
