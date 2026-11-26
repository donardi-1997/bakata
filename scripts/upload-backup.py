#!/usr/bin/env python3
"""Upload a verified local backup with checksum validation; manifest is last."""
import base64
import hashlib
import pathlib
import re
import sys

import boto3
from botocore.config import Config

BUCKET = "bakata-dev-backups-765761474007-us-east-1"
FILES = ("database.sql.gz", "wordpress.tar.gz", "host-config.tar.gz",
         "git-commit", "image-ids", "SHA256SUMS")

def main():
    directory = pathlib.Path(sys.argv[1]).resolve(strict=True)
    if directory.parent != pathlib.Path("/var/backups/bakata") or not re.fullmatch(
        r"backup-[0-9]{8}T[0-9]{6}Z", directory.name
    ):
        raise ValueError("Invalid backup directory")
    session = boto3.Session(region_name="us-east-1")
    identity = session.client("sts").get_caller_identity()
    if ":assumed-role/BakataDevSSMRole/" not in identity["Arn"]:
        raise RuntimeError("Unexpected AWS identity")
    client = session.client("s3", config=Config(retries={"mode": "standard", "max_attempts": 4}))
    manifest = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        manifest[name] = digest
    if set(manifest) != set(FILES[:-1]):
        raise ValueError("Unexpected manifest entries")
    for name in FILES:
        path = directory / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 5 * 1024**3:
            raise ValueError("Invalid file or single PUT size limit exceeded")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256")
            if name != "SHA256SUMS" and digest.hexdigest() != manifest[name]:
                raise RuntimeError("Local checksum mismatch")
            checksum = base64.b64encode(digest.digest()).decode("ascii")
            stream.seek(0)
            response = client.put_object(Bucket=BUCKET, Key=f"dev/{directory.name}/{name}",
                                         Body=stream, ServerSideEncryption="AES256",
                                         ChecksumSHA256=checksum)
        if response.get("ChecksumSHA256") != checksum:
            raise RuntimeError("S3 checksum missing or mismatched")
        print(f"S3 verified: {directory.name}/{name}", flush=True)
    print("S3 recovery point complete", flush=True)

if __name__ == "__main__":
    main()
