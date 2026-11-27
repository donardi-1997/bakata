#!/usr/bin/env python3
"""Rehearse catalog-only replacement and rollback in a private temporary tree.
Never starts WordPress, mounts a live volume, deploys or contacts a provider.
"""
import argparse
import hashlib
import json
import re
import stat
import tempfile
import zipfile
from pathlib import Path
# The existing builder has a hyphenated filename.
import importlib.util
spec = importlib.util.spec_from_file_location("harden_dropify", Path(__file__).with_name("harden-dropify.py"))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
build, SHA, ROOT = builder.build, builder.SHA, builder.ROOT

ORIGINAL_TREE = "900f3149c2e512ac52836f37bc369c8a2f424784c0faf4d7c404a818d4ba9f6e"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def path_ok(name):
    return all(part not in ("", ".", "..") and re.fullmatch(r"[A-Za-z0-9_.@-]+", part)
               for part in name.split("/"))


def archive_files(path):
    if path.stat().st_size > 1048576:
        raise ValueError("Archive too large")
    files = {}
    total = 0
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            if not item.filename.startswith(ROOT):
                raise ValueError("Unexpected ZIP root")
            name = item.filename[len(ROOT):]
            mode = stat.S_IFMT(item.external_attr >> 16)
            if item.is_dir():
                if mode not in (0, stat.S_IFDIR) or (name and not path_ok(name.rstrip("/"))):
                    raise ValueError("Unexpected directory")
                continue
            if not path_ok(name) or name in files or mode not in (0, stat.S_IFREG):
                raise ValueError("Unsafe archive entry")
            total += item.file_size
            if item.file_size > 2097152 or total > 8388608 or len(files) >= 53:
                raise ValueError("Unexpected archive size")
            files[name] = archive.read(item)
    if len(files) != 53:
        raise ValueError("Unexpected file count")
    return files


def tree_digest(files):
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode("ascii") + b"\0" + sha(data).encode("ascii") + b"\n")
    return digest.hexdigest()


def materialize(directory, files):
    directory.mkdir()
    for name, data in files.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(data)


def verify(directory, expected):
    found = {}
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Missing plugin directory")
    for entry in directory.rglob("*"):
        if entry.is_symlink():
            raise ValueError("Symlink in staged plugin")
        if entry.is_dir():
            continue
        name = entry.relative_to(directory).as_posix()
        if not entry.is_file() or name not in expected or entry.stat().st_size > 2097152:
            raise ValueError("Unexpected staged file")
        found[name] = entry.read_bytes()
    if found != expected:
        raise ValueError("Staged files differ")
    return tree_digest(found)


def rehearse(original, candidate, expected_sha):
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("Explicit candidate SHA-256 required")
    if original.stat().st_size > 1048576 or sha(original.read_bytes()) != SHA:
        raise ValueError("Unexpected original ZIP")
    if candidate.stat().st_size > 1048576 or sha(candidate.read_bytes()) != expected_sha:
        raise ValueError("Unexpected candidate ZIP")
    old = archive_files(original)
    new = archive_files(candidate)
    if tree_digest(old) != ORIGINAL_TREE or old.keys() != new.keys() or old == new:
        raise ValueError("Unexpected source or candidate tree")
    with tempfile.TemporaryDirectory(prefix="bakata-dropify-rehearsal-") as temp:
        root = Path(temp)
        # Rebuild with the checked-out catalog-only patch. Compare file bytes rather
        # than ZIP metadata so release tooling differences cannot mask a changed file.
        rebuilt = root / "rebuilt.zip"
        build(original, rebuilt, catalog_only=True)
        if archive_files(rebuilt) != new:
            raise ValueError("Candidate differs from catalog-only build at this revision")
        plugins = root / "plugins"
        plugins.mkdir()
        active = plugins / "wc-dropi-integration"
        staged = root / "candidate"
        saved = root / "original"
        rejected = root / "rejected"
        materialize(active, old)
        materialize(staged, new)
        verify(active, old)
        verify(staged, new)

        # Rehearse a stopped application and same-filesystem directory renames.
        # Interruption after the first rename: only restore the verified saved tree.
        active.rename(saved)
        verify(saved, old)
        if active.exists():
            raise ValueError("Unexpected active path")
        saved.rename(active)
        verify(active, old)

        # Normal replacement, then explicit rollback.
        active.rename(saved)
        staged.rename(active)
        verify(active, new)
        verify(saved, old)
        active.rename(rejected)
        saved.rename(active)
        verify(active, old)
        verify(rejected, new)
        if list(plugins.iterdir()) != [active]:
            raise ValueError("More than one plugin in active directory")
        report = {"status":"passed", "original_zip_sha256":SHA,
                  "candidate_zip_sha256":expected_sha,
                  "original_tree_sha256":tree_digest(old),
                  "candidate_tree_sha256":tree_digest(new),
                  "files":len(old), "changed_files":sum(old[n]!=new[n] for n in old),
                  "interruption_recovered":True, "rollback_verified":True,
                  "live_installation_modified":False, "provider_queries":0}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(rehearse(args.original, args.candidate, args.candidate_sha256), sort_keys=True))
