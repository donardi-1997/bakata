"""Offline guard: research images use digest-pinned bases and hash-locked pip installs.

This proves the *inputs* are immutable references; it does not prove the referenced
artifacts were reviewed, scanned or that a rebuild is bit-for-bit identical.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
IMAGES = [
    "infra/research-aws/proxy.Dockerfile",
    "infra/research-aws/coordinator.Dockerfile",
    "infra/research-worker/Dockerfile",
    "services/intelligence/Dockerfile",
]
LOCK = "infra/research-aws/coordinator-requirements.lock"
FROM = re.compile(r"^\s*FROM\s+(\S+)", re.I | re.M)
PINNED = re.compile(r"^[a-z0-9./_-]+(:[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}$")
LOCK_LINE = re.compile(r"^[a-z0-9][a-z0-9._-]*==[A-Za-z0-9.+!_-]+ --hash=sha256:[0-9a-f]{64}$")


def violations(dockerfile_text):
    found = []
    stages = set(re.findall(r"^\s*FROM\s+\S+\s+AS\s+(\S+)", dockerfile_text, re.I | re.M))
    for ref in FROM.findall(dockerfile_text):
        if ref not in stages and not PINNED.fullmatch(ref):
            found.append("unpinned base " + ref)
    for line in re.findall(r"^\s*RUN\s+.*$", dockerfile_text, re.M):
        if re.search(r"\bpip3?\s+install\b", line):
            for flag in ("--require-hashes", "--no-deps", "--only-binary=:all:", "-r "):
                if flag not in line:
                    found.append("pip install without " + flag.strip())
        if re.search(r"\b(apt-get|apk)\s+(install|add)\b", line):
            found.append("unpinned OS package install")
    return found


class ImagePinTests(unittest.TestCase):
    def test_research_images_are_pinned(self):
        for rel in IMAGES:
            with self.subTest(rel):
                self.assertEqual(violations((ROOT / rel).read_text()), [])

    def test_lock_is_fully_hashed_and_unique(self):
        lines = [l for l in (ROOT / LOCK).read_text().splitlines() if l and not l.startswith("#")]
        self.assertTrue(lines)
        names = [l.split("==")[0] for l in lines]
        self.assertEqual(len(names), len(set(names)))
        for line in lines:
            self.assertRegex(line, LOCK_LINE)
        self.assertIn("boto3", names)

    def test_guard_rejects_unsafe_mutations(self):
        digest = "@sha256:" + "a" * 64
        bad = {
            "FROM python:3.12-slim\n": "unpinned base",
            "FROM python:latest" + "\n": "unpinned base",
            "FROM python:3.12-slim" + digest + "\nRUN pip install boto3\n": "pip install without",
            "FROM python:3.12-slim" + digest + "\nRUN pip install --require-hashes -r x\n": "--no-deps",
            "FROM debian" + digest + "\nRUN apt-get install -y curl\n": "OS package",
        }
        for text, expected in bad.items():
            with self.subTest(text):
                self.assertTrue(any(expected in v for v in violations(text)), violations(text))
        ok = "FROM a/b:1" + digest + " AS core\nFROM core\n"
        self.assertEqual(violations(ok), [])


if __name__ == "__main__":
    unittest.main()
