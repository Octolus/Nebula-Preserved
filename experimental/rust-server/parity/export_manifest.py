"""List reviewed source/report files; never include operational run state."""
import json
from pathlib import Path
import re
from common import HERE, sha256, write_json


def main():
    entries = []
    for folder in (HERE, HERE / "fixtures", HERE / "admin"):
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.suffix not in (".py", ".md", ".json") or path.name == "export-manifest.json":
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r"(?i)[a-z]:[/\\]{1,2}(?:users|codex|nebula-preserved)(?:[/\\]|$)", text):
                raise ValueError("PERSONAL_PATH_IN_EXPORTABLE_FILE:" + path.name)
            entries.append({"source": path.relative_to(HERE).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size})
    evidence = json.loads((HERE / "admin-verification.json").read_text())
    changed_sources = [row["source"] for row in evidence["harness_sources"]
                       if not (HERE / row["source"]).is_file() or sha256(HERE / row["source"]) != row["sha256"]]
    manifest = {"format_version": 1, "files": entries, "file_count": len(entries),
                "source_identity": "PORTABILITY_DERIVATIVE_AWAITS_FULL_RERUN" if changed_sources else "MATCHES_LATEST_RECORDED_ADMIN_RUN_SOURCES",
                "changed_sources_since_recorded_run": changed_sources,
                "recorded_evidence": [{"source": name, "sha256": sha256(HERE / name)} for name in ("verification.json", "configured-verification.json", "admin-verification.json", "combined-verification.json")],
                "exclude": ["runs/**", "temp/**", "__pycache__/**", "*.exe", "*.db", "*.db-*", "*.sqlite*", "*-stderr.log"],
                "provenance": "Authored harness, synthetic fixtures and path-redacted evidence only; no original assets or real credentials", "one_to_one_parity": "NOT_PROVEN"}
    write_json(HERE / "export-manifest.json", manifest)
    print(json.dumps({"exportable_files": len(entries), "bytes": sum(row["bytes"] for row in entries)}))


if __name__ == "__main__":
    main()
