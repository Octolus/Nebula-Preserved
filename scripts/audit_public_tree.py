"""Read-only publication hygiene check over tracked and unignored files."""
from pathlib import Path
import json
import os
import re
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_NAMES = {"GameAssembly.dll", "global-metadata.dat", "preservation.sqlite3"}
FORBIDDEN_SUFFIXES = {".exe", ".sqlite", ".sqlite3", ".db", ".dmp", ".pfx", ".p12", ".key", ".pem", ".zip"}
PRIVATE_PATTERNS = {
    "private workspace path": re.compile(r"[A-Z]:[\\/](?:Users[\\/](?!Public\b|USER\b|USERNAME\b)[^\\/\s]+|Codex[\\/]\d{4}-\d{2}-\d{2})", re.I),
    "real Steam account ID": re.compile(r"\b7656119\d{10}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "AWS access key": re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
}
# Exact authored fixture assertion only. Keep every other account-shaped value
# visible to the scanner, including this value in any other file. Split the
# literal here so the scanner's own configuration is not a second exception.
SYNTHETIC_ACCOUNTS = {
    "admin-panel/e2e/panel.spec.ts": {"7656119" + "0000000001"},
    # Authored Rust oracle fixtures use valid-shaped synthetic identifiers to
    # exercise Steam-format checks. These are exact file/value exceptions.
    "experimental/rust-server/tests/access_contracts.rs": {"7656119" + "0000000001"},
    "experimental/rust-server/interop/run_interop.py": {"7656119" + "0000000001"},
    "experimental/rust-server/tests/character_contracts.rs": {"7656119" + "8000000001", "7656119" + "8000000002"},
    "experimental/rust-server/tests/character_python_vectors.json": {"7656119" + "8000000001"},
    "experimental/rust-server/tests/character_python_vectors.py": {"7656119" + "8000000001"},
    "experimental/rust-server/tests/lifecycle_contracts.rs": {"7656119" + "8000000001", "7656119" + "8000000002"},
    # Backend and host-policy tests use the same valid-shaped synthetic style.
    "backend/tests/test_diagnostic_logging.py": {"7656119" + "8000000001", "7656119" + "8000000002", "7656119" + "8000000003"},
    "backend/tests/test_request_line_limits.py": {"7656119" + "8000000000"},
    "deployment/ansible/tests/test_host_policy.py": {"7656119" + "0000000991"},
}
# Shipped game asset names that can coincide with a local username or computer
# name. Exact file/phrase exceptions; only the machine-identity rules skip them.
GAME_ASSET_PHRASES = {
    "protocol/item-display-metadata.json": {"Tshirt Oc" + "to"},
}
MACHINE_LABELS = ("current Windows username", "current computer name")

for label, value in zip(MACHINE_LABELS, (os.environ.get("USERNAME"), socket.gethostname())):
    if value and len(value) >= 4:
        PRIVATE_PATTERNS[label] = re.compile(r"(?<!\w)" + re.escape(value) + r"(?!\w)", re.I)


def private_content_issues(name, content):
    issues = []
    scrubbed = content
    for phrase in GAME_ASSET_PHRASES.get(name, ()):
        scrubbed = scrubbed.replace(phrase, "")
    for label, pattern in PRIVATE_PATTERNS.items():
        if label == "real Steam account ID":
            allowed = SYNTHETIC_ACCOUNTS.get(name, set())
            found = any(match.group(0) not in allowed for match in pattern.finditer(content))
        else:
            found = pattern.search(scrubbed if label in MACHINE_LABELS else content) is not None
        if found:
            issues.append({"path": name, "issue": label})
    return issues


def main():
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, check=True, stdout=subprocess.PIPE,
    )
    files = sorted(set(p.decode("utf-8") for p in result.stdout.split(b"\0") if p))
    issues = []
    total = 0
    for name in files:
        path = ROOT / name
        if not path.is_file():
            continue
        if path.is_symlink():
            issues.append({"path": name, "issue": "symlink requires review"})
            continue
        total += path.stat().st_size
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            issues.append({"path": name, "issue": "private/generated/binary artifact"})
        if path.stat().st_size > 25 * 1024 * 1024:
            issues.append({"path": name, "issue": "file exceeds 25 MiB"})
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        issues.extend(private_content_issues(name, content))
    print(json.dumps({"files_checked": len(files), "bytes": total, "issues": issues}, indent=2))
    return int(bool(issues))


if __name__ == "__main__":
    sys.exit(main())
