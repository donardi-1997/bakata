import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location("rehearsal",Path(__file__).with_name("dropify-rollout-rehearsal.py"))
r=importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class RehearsalTests(unittest.TestCase):
    def test_paths(self):
        for name in ("../secret","a/../../b","/absolute","a//b","a\\b","a/./b"):
            self.assertFalse(r.path_ok(name))
        self.assertTrue(r.path_ok("js/sweetalert2@11.js"))

    def test_zip_rejects_traversal_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with zipfile.ZipFile(root/"traversal.zip","w") as archive:
                archive.writestr(r.ROOT+"../outside",b"bad")
            with self.assertRaises(ValueError):
                r.archive_files(root/"traversal.zip")
            with zipfile.ZipFile(root/"link.zip","w") as archive:
                info=zipfile.ZipInfo(r.ROOT+"link")
                info.create_system=3
                info.external_attr=0o120777<<16
                archive.writestr(info,b"/tmp")
            with self.assertRaises(ValueError):
                r.archive_files(root/"link.zip")

    def test_directory_integrity_and_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            old={"one.php":b"old","js/test@1.js":b"script"}
            r.materialize(root/"active",old)
            self.assertEqual(r.verify(root/"active",old),r.tree_digest(old))
            (root/"active"/"one.php").write_bytes(b"modified")
            with self.assertRaises(ValueError):
                r.verify(root/"active",old)
            (root/"active"/"one.php").write_bytes(b"old")
            (root/"active"/"unexpected").symlink_to(root/"active"/"one.php")
            with self.assertRaises(ValueError):
                r.verify(root/"active",old)

    def test_explicit_digest(self):
        with self.assertRaises(ValueError):
            r.rehearse(Path("unread"),Path("unread"),"not-a-sha")


if __name__=="__main__":
    unittest.main()
