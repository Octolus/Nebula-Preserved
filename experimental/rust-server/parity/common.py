"""Owned scratch paths and wire-neutral snapshot helpers; no reference imports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def scratch(path: Path) -> Path:
    path = Path(path)
    result = (path if path.is_absolute() else HERE / path).resolve()
    if not result.is_relative_to(HERE):
        raise ValueError("state and reports must stay under the owned harness directory")
    result.mkdir(parents=True, exist_ok=True)
    return result


def environment(temp: Path) -> dict[str, str]:
    temp = scratch(temp)
    env = dict(os.environ)
    env.update(TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp),
               PYTHONDONTWRITEBYTECODE="1", PYTHONPYCACHEPREFIX=str(temp / "pycache"),
               XDG_CACHE_HOME=str(temp / "cache"))
    return env


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    scratch(path.parent)
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def snapshot(db) -> dict:
    tables = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        quoted = '"' + name.replace('"', '""') + '"'
        columns = [{"name": row[1], "type": row[2].upper()} for row in db.execute("PRAGMA table_info(" + quoted + ")")]
        rows = []
        for row in db.execute("SELECT * FROM " + quoted):
            rows.append({col["name"]: {"blob_hex": value.hex()} if isinstance(value, bytes) else value
                         for col, value in zip(columns, row)})
        rows.sort(key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=True, allow_nan=False))
        tables[name] = {"columns": columns, "rows": rows}
    return {"tables": tables}
