import gzip
import importlib.util
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
import unittest

spec=importlib.util.spec_from_file_location("preflight",Path(__file__).with_name("dropify-dev-preflight.py"))
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now=datetime(2026,11,26,22,tzinfo=timezone.utc)
        self.root=Path(self.temp.name)/"backup-20261126T210000Z"
        self.root.mkdir(mode=0o700)
        for name in p.BACKUP_FILES:
            data=b"fixture"
            if name.endswith(".gz"):
                data=gzip.compress(data)
            elif name=="git-commit":
                data=b"a"*40+b"\n"
            path=self.root/name
            path.write_bytes(data)
            path.chmod(0o600)
        self.manifest=self.root/"SHA256SUMS"
        self.manifest.write_text("".join(f"{p.digest(self.root/name)}  {name}\n" for name in sorted(p.BACKUP_FILES)))
        self.manifest.chmod(0o600)

    def test_integrity_not_restore(self):
        report=p.backup_status(self.root,self.now)
        self.assertEqual(report["status"],"integrity-verified")
        self.assertFalse(report["restore_tested"])

    def test_tamper_and_permissions(self):
        path=self.root/"database.sql.gz"
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            p.backup_status(self.root,self.now)
        path.chmod(0o600)
        path.write_bytes(b"invalid")
        with self.assertRaises(ValueError):
            p.backup_status(self.root,self.now)

    def test_symlink_and_manifest_traversal(self):
        path=self.root/"image-ids"
        path.unlink()
        path.symlink_to(self.root/"git-commit")
        with self.assertRaises(ValueError):
            p.backup_status(self.root,self.now)
        self.manifest.write_text("a"*64+"  ../secret\n")
        with self.assertRaises(ValueError):
            p.backup_status(self.root,self.now)

    def test_comparison(self):
        expected={"one":"a","two":"b"}
        self.assertEqual(p.compare(expected,{"present":True,"files":expected})["status"],"exact-original")
        result=p.compare(expected,{"present":True,"files":{"one":"a","extra":"c"}})
        self.assertEqual((result["matching"],result["missing"],result["extra"]),(1,1,1))
        self.assertEqual(result["status"],"requires-review")
        self.assertEqual(p.compare(expected,{"present":False,"files":{}})["status"],"not-detected")


if __name__=="__main__":
    unittest.main()
