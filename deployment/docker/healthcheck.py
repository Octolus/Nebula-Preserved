"""Process health only; never asserts game readiness or networking parity."""
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen


def validate(http, runtime, now):
    generation = runtime.get('generation')
    return (http.get('service') == 'nebula-preservation' and http.get('managed_instances') is True and
            runtime.get('format_version') == 1 and isinstance(runtime.get('instances'), list) and
            type(generation) in (int, float) and -2 <= now-generation <= 20)


def main():
    try:
        with urlopen('http://127.0.0.1:8080/preservation/health', timeout=2) as response:
            http = json.load(response)
            if response.status != 200: return 1
        runtime = json.loads(Path('/var/lib/nebula/managed-instance-runtime.json').read_text(encoding='utf-8'))
        return 0 if validate(http, runtime, time.time()) else 1
    except (OSError, ValueError, TypeError): return 1


if __name__ == '__main__': sys.exit(main())
