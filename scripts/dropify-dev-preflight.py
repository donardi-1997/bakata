#!/usr/bin/env python3
"""Local root-only preflight. Never restores, reads credentials as text, boots WP or contacts Dropi."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from datetime import datetime, timezone, timedelta
import zipfile

ORIGINAL = "bf23c6b1c5dd640aab3d38e3f370a41fbd60139ac60a1ce5f0347a059e9b6700"
BACKUP_FILES = {"database.sql.gz","wordpress.tar.gz","host-config.tar.gz","git-commit","image-ids"}
ROOT = "wc-dropi-integration/"


def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def private(path, directory=False):
    info=path.lstat()
    expected=stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode & 0o077:
        raise ValueError("Backup path is not private or has an unexpected type")


def backup_status(path,now):
    private(path,True)
    if not re.fullmatch(r"backup-[0-9]{8}T[0-9]{6}Z",path.name):
        raise ValueError("Unexpected backup directory")
    stamp=datetime.strptime(path.name.removeprefix("backup-"),"%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    if not timedelta(0)<=now-stamp<=timedelta(hours=48):
        raise ValueError("Backup is stale or has a future date")
    manifest=path/"SHA256SUMS"
    private(manifest)
    if manifest.stat().st_size>4096:
        raise ValueError("Invalid manifest size")
    entries={}
    for line in manifest.read_text(encoding="ascii").splitlines():
        match=re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9.-]+)",line)
        if not match or match[2] not in BACKUP_FILES or match[2] in entries:
            raise ValueError("Invalid backup manifest")
        entries[match[2]]=match[1]
    if set(entries)!=BACKUP_FILES:
        raise ValueError("Incomplete backup manifest")
    for name,expected in entries.items():
        file=path/name
        private(file)
        if file.stat().st_size<=0 or digest(file)!=expected:
            raise ValueError("Backup integrity failed")
    # Validate compression without extracting any private content.
    for name in ("database.sql.gz","wordpress.tar.gz","host-config.tar.gz"):
        subprocess.run(["gzip","-t",str(path/name)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=300)
    commit=(path/"git-commit").read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40}",commit):
        raise ValueError("Invalid backup commit")
    return {"status":"integrity-verified","created_at":stamp.isoformat(),"commit":commit,"restore_tested":False}


def reference(original):
    if original.stat().st_size>1024*1024 or digest(original)!=ORIGINAL:
        raise ValueError("Unexpected original ZIP")
    with zipfile.ZipFile(original) as archive:
        return {item.filename[len(ROOT):]:hashlib.sha256(archive.read(item)).hexdigest()
                for item in archive.infolist() if item.filename.startswith(ROOT) and not item.is_dir()}


# Execute only this PHP code, never load wp-config.php or WordPress/plugin code.
PHP = r'''
$root='/var/www/html/wp-content/plugins/wc-dropi-integration';
if (!is_dir($root) || is_link($root)) { echo json_encode(['present'=>false,'files'=>[]]); exit; }
$result=[];
$it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root,FilesystemIterator::SKIP_DOTS));
foreach ($it as $file) {
    if (count($result)>=500 || $file->isLink() || !$file->isFile() || $file->getSize()>2*1024*1024) {
        throw new RuntimeException('Unexpected plugin tree');
    }
    $relative=substr($file->getPathname(),strlen($root)+1);
    $hash=hash_file('sha256',$file->getPathname());
    if ($hash===false) { throw new RuntimeException('Unreadable file'); }
    $result[$relative]=$hash;
}
echo json_encode(['present'=>true,'files'=>$result],JSON_THROW_ON_ERROR);
'''


def compare(expected,observed):
    if not observed["present"]:
        return {"status":"not-detected","matching":0,"different":0,"missing":len(expected),"extra":0}
    files=observed["files"]
    if not isinstance(files,dict) or len(files)>500:
        raise ValueError("Invalid plugin inventory")
    counts={"matching":sum(files.get(k)==v for k,v in expected.items()),
            "different":sum(k in files and files[k]!=v for k,v in expected.items()),
            "missing":len(set(expected)-set(files)),"extra":len(set(files)-set(expected))}
    return dict(counts,status="exact-original" if counts["matching"]==len(expected) and not counts["extra"] else "requires-review")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup",type=Path,required=True)
    parser.add_argument("--original",type=Path,required=True)
    args=parser.parse_args()
    if os.geteuid()!=0 or Path.cwd()!=Path("/home/ubuntu/bakata"):
        parser.error("Run as root from the documented dev repository")
    if args.backup.parent!=Path("/var/backups/bakata"):
        parser.error("Select an existing backup under the private dev backup directory")
    try:
        private(args.backup.parent,True)
        expected=reference(args.original)
        backup=backup_status(args.backup,datetime.now(timezone.utc))
        data=subprocess.run(["docker","compose","exec","-T","wordpress","php","-r",PHP],
                            check=True,capture_output=True,timeout=30)
        if len(data.stdout)>131072:
            raise ValueError("Plugin inventory too large")
        plugin=compare(expected,json.loads(data.stdout))
        print(json.dumps({"backup":backup,"plugin":plugin,"live_query_ready":False,
                          "next":"isolated-restore-and-authorization"},sort_keys=True))
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):
        # Never print exception details from private filesystem or Docker.
        parser.exit(1,"Preflight blocked: verify backup, ZIP and local container privately.\n")


if __name__=="__main__":
    main()
