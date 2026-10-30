"""Compile/run the real Windows profile gate using only new disposable files."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if (output.exists() or output.is_relative_to(HERE.parents[2]) or
            'steamapps' in [part.lower() for part in output.parts]):
        raise ValueError('Use a new absolute output directory outside the source')
    output.mkdir(parents=True)
    (output/'RemoteTransportPin.h').write_text(
        '#define NEBULA_REMOTE_TRANSPORT_SHA256 "' + '0'*64 + '"\n', encoding='ascii')
    executable = output/'test_remote_profile.exe'
    subprocess.run([
        str(args.cxx), '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-municode',
        '-I', str(output), str(HERE/'test_remote_profile.cpp'), '-o', str(executable),
        '-lbcrypt', '-static', '-static-libgcc', '-static-libstdc++',
    ], check=True)
    result = subprocess.run([str(executable), str(output/'profile')],
                            check=True, capture_output=True, text=True)
    if 'TOTAL 23 remote profile checks passed' not in result.stdout:
        raise ValueError('Actual Windows profile check count differs')
    print(json.dumps({'windows_profile_checks': 23, 'game_launched': False,
                      'listener_started': False, 'passed': True}))


if __name__ == '__main__':
    main()
