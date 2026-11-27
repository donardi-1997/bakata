"""Assemble a minimal fixture-only Docker context from validated public artifacts."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

ROOT=Path(__file__).resolve().parent.parent


def extract(archive,dest,expected_root):
    with zipfile.ZipFile(archive) as source:
        entries=source.infolist()
        if len(entries)>20000 or sum(x.file_size for x in entries)>256*1024*1024:
            raise ValueError("Plugin archive exceeds build budget")
        names=set()
        for entry in entries:
            p=PurePosixPath(entry.filename)
            if (p.is_absolute() or not p.parts or p.parts[0]!=expected_root
                or ".." in p.parts or "\\" in entry.filename
                or stat.S_ISLNK(entry.external_attr>>16) or p in names):
                raise ValueError("Unexpected plugin archive path")
            names.add(p)
        source.extractall(dest)


def prepare(original,candidate,woo,dest,expected):
    # Rebuild the candidate locally from the audited distribution. The ZIP bytes
    # are deterministic for the same input and builder; reject a different build.
    from importlib import import_module
    import tempfile
    import subprocess
    import sys
    if hashlib.sha256(candidate.read_bytes()).hexdigest()!=expected:
        raise ValueError("Candidate hash mismatch")
    with tempfile.TemporaryDirectory() as temp:
        rebuilt=Path(temp)/"catalog.zip"
        subprocess.run([sys.executable,str(ROOT/"scripts/harden-dropify.py"),str(original),str(rebuilt),"--catalog-only"],check=True)
        if hashlib.sha256(rebuilt.read_bytes()).hexdigest()!=expected:
            raise ValueError("Candidate differs from reviewed builder")
    dest.mkdir(mode=0o700,exist_ok=False)
    plugins=dest/"plugins"
    plugins.mkdir()
    extract(candidate,plugins,"wc-dropi-integration")
    extract(woo,plugins,"woocommerce")
    for name in ("Dockerfile","wp-config.php","run-fixture.sh","validate-request.php","catalog-egress-policy.php"):
        shutil.copyfile(ROOT/"infra/research-worker"/name,dest/name)
    shutil.copyfile(ROOT/"tools/dropify-quarantine/sandbox-fixture.php",dest/"sandbox-fixture.php")
    shutil.copyfile(ROOT/"scripts/dropify-capture-page.php",dest/"dropify-capture-page.php")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("original","candidate","woo","dest"):
        p.add_argument(name,type=Path)
    p.add_argument("--candidate-sha256",required=True)
    a=p.parse_args()
    prepare(a.original,a.candidate,a.woo,a.dest,a.candidate_sha256)
