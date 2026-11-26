#!/usr/bin/env python3
"""Inventory a local Dropify ZIP without extracting or executing its contents."""
import argparse
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

PATTERNS = {
    "hooks": r"\b(?:add_action|add_filter|register_rest_route|register_activation_hook)\s*\(",
    "network": r"\b(?:wp_remote_\w+|curl_exec|file_get_contents)\s*\(",
    "credentials": r"\b(?:get_option|update_option|add_option|delete_option)\s*\(",
    "orders": r"\b(?:wc_create_order|wc_get_order|update_status|payment_complete)\s*\(",
    "catalog": r"\b(?:WC_Product\w*|wc_get_product|wp_insert_post|set_stock_quantity)\b",
    "permissions": r"\b(?:current_user_can|check_admin_referer|wp_verify_nonce|permission_callback)\b",
    "storage": r"\b(?:wpdb|update_post_meta|get_post_meta|custom_order_tables)\b",
    "scheduling": r"\b(?:wp_schedule_event|wp_schedule_single_event|as_enqueue_async_action|as_schedule_single_action)\b",
}
LIMIT = 64 * 1024 * 1024

def audit(path):
    if path.stat().st_size > LIMIT:
        raise ValueError("Archive exceeds size limit")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    findings = []
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(e.file_size for e in entries) > LIMIT:
            raise ValueError("Expanded archive exceeds limits")
        seen = set()
        for entry in entries:
            name = entry.filename
            p = PurePosixPath(name)
            if (p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name
                    or name in seen or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError("Unsafe or duplicate archive member")
            seen.add(name)
            if entry.is_dir() or p.suffix.lower() not in {".php", ".js"}:
                continue
            source = archive.read(entry).decode("utf-8", errors="replace")
            for category, pattern in PATTERNS.items():
                for match in re.finditer(pattern, source, re.IGNORECASE):
                    if len(findings) >= 20000:
                        raise ValueError("Finding limit exceeded")
                    findings.append({"file": name, "line": source.count("\n", 0, match.start()) + 1,
                                     "category": category})
    return {"sha256": digest, "findings": findings,
            "limitations": "Heuristic inventory only; not a security or compatibility verdict."}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.archive), indent=2, ensure_ascii=True))
