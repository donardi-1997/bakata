#!/usr/bin/env python3
"""Validate the cumulative Dropify archive offline without installing it."""
import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUITES = ('test-dropify-hardening.php', 'test-dropify-dispatch.php', 'test-dropify-hpos.php')


def verify(original, php):
    with tempfile.TemporaryDirectory(prefix='bakata-dropify-') as temp:
        work = Path(temp)
        patched = work / 'patched.zip'
        subprocess.run([sys.executable, str(REPO / 'scripts/harden-dropify.py'), str(original.resolve()), str(patched)], check=True)
        with zipfile.ZipFile(patched) as archive:
            # Output is generated from the exact hash-pinned input archive.
            archive.extractall(work / 'source')
        root = work / 'source/wc-dropi-integration'
        files = sorted(root.rglob('*.php'))
        if len(files) != 35:
            raise RuntimeError('Unexpected PHP file count')
        for path in files:
            subprocess.run([php, '-l', str(path)], check=True, stdout=subprocess.DEVNULL)
        print(f'{len(files)} PHP files linted', flush=True)
        for suite in SUITES:
            subprocess.run([php, str(REPO / 'scripts' / suite), str(root)], check=True)
    print('Cumulative offline validation passed; no plugin installed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('--php', default='php')
    args = parser.parse_args()
    verify(args.original, args.php)
