"""Validate brand parity, semantic contrast and local design-system assets."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

root = Path(__file__).resolve().parents[1]
theme = root / "wp-content/themes/bakata"
tokens = json.loads((theme / "assets/css/design-system.json").read_text())
brand = json.loads((root / "brand/design-tokens/tokens.json").read_text())
config = json.loads((theme / "theme.json").read_text())
colors = tokens["color"]
css = (theme / "assets/css/design-system.css").read_text()
palette = {p["slug"]: p["color"] for p in config["settings"]["color"]["palette"]}
assert all(palette[k] == v for k, v in brand["color"].items()), "Brand palette drift"
assert all(colors[k] == brand["semantic"][v] for k, v in {
    "background": "background", "text": "text", "primary": "primary",
    "onPrimary": "onPrimary", "surfaceMuted": "surface", "accentDecorative": "accent"
}.items()), "Semantic color drift"
for key, value in colors.items():
    slug = re.sub(r"[A-Z]", lambda m: "-" + m[0].lower(), key)
    assert f"--bk-{slug}: {value};" in css, f"CSS token drift: {key}"

def luminance(hex_color):
    rgb = [int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in rgb]
    return sum(x * y for x, y in zip(linear, (.2126, .7152, .0722)))

def contrast(a, b):
    light, dark = sorted((luminance(colors[a]), luminance(colors[b])), reverse=True)
    return (light + .05) / (dark + .05)

for a, b, minimum in [
    ("text", "background", 4.5), ("text", "surface", 4.5),
    ("textMuted", "background", 4.5), ("textMuted", "surface", 4.5),
    ("textMuted", "surfaceMuted", 4.5), ("onPrimary", "primary", 4.5),
    ("onPrimary", "primaryHover", 4.5), ("primary", "surfaceMuted", 4.5),
    ("primary", "background", 4.5), ("accentText", "background", 4.5),
    ("error", "surface", 4.5), ("error", "background", 4.5),
    ("success", "surface", 4.5), ("border", "surface", 3),
    ("border", "background", 3), ("focus", "background", 3),
]:
    ratio = contrast(a, b)
    assert ratio >= minimum, f"{a}/{b}: {ratio:.2f} < {minimum}"
    print(f"{a}/{b}: {ratio:.2f}:1")
for path in (theme / "assets/brand").glob("*.svg"):
    ET.parse(path)
sprite = ET.parse(theme / "assets/icons/sprite.svg")
ids = {s.attrib["id"] for s in sprite.getroot()}

class PreviewParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        for key, val in attrs:
            if key not in ("src", "href") or not val or val.startswith("#"):
                continue
            path, _, fragment = val.partition("#")
            resolved = (root / "docs" / path).resolve()
            assert resolved.is_relative_to(root) and resolved.is_file(), val
            if tag == "use":
                assert fragment in ids, val

PreviewParser().feed((root / "docs/design-system-preview.html").read_text())
print("Design system checks passed (static validation only).")
