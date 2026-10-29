"""Compile actual request consumer against synthetic, offline host fixtures."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
OLD = "4d6023c1d55ed94530969c0af947ac22313f3a77870a89c66873cf34e800fe83"
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("cxx", "old-source", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args(); out = a.output.resolve()
    if out.exists() or out.is_relative_to(HERE) or "steamapps" in [x.lower() for x in out.parts]:
        raise ValueError("Fresh isolated fixture output required")
    if sha(a.old_source) != OLD:
        raise ValueError("Exact old consumer required")
    out.mkdir(parents=True)
    results = {}
    for name, source in (("new", HERE / "NebulaPublicAccess.cpp"), ("old", a.old_source.resolve())):
        exe = out / (name + "-consumer.exe")
        subprocess.run([str(a.cxx), "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                        '-DNPA_CONSUMER_SOURCE="' + source.as_posix() + '"',
                        str(HERE / "test_public_consumer.cpp"), "-o", str(exe), "-lcrypt32", "-lbcrypt"], check=True)
        result = subprocess.run([str(exe), str(out / (name + "-synthetic-profile"))], capture_output=True, text=True)
        if name == "new" and (result.returncode != 0 or "TOTAL 10 actual consumer checks passed" not in result.stdout):
            raise ValueError("New actual consumer failed: " + result.stderr)
        if name == "old" and (result.returncode != 1 or result.stderr.strip() != "FAIL stripped_engine_remote_loopback_should_forward"):
            raise ValueError("Old consumer did not fail the exact regression: " + result.stderr)
        results[name] = dict(returncode=result.returncode, stdout=result.stdout.strip(), stderr=result.stderr.strip(), source_sha256=sha(source))
    receipt = dict(format="actual-public-loopback-consumer-checks-v1", passed=True, actual_new_cpp_checks=10,
                   fixture_sha256=sha(HERE / "test_public_consumer.cpp"), results=results,
                   game_or_sidecar_loaded=False, listener_or_connection_created=False, only_synthetic_test_credential=True)
    (out / "checks.PRIVATE.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "actual_consumer_checks": 10, "old_exact_regression_failed": True}))

if __name__ == "__main__": main()
