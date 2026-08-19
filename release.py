#!/usr/bin/env python3
"""Create or update a public GitHub release from the matching changelog entry.

Usage: python3 release.py <version>  (for example: python3 release.py 1.0.0)
"""
import sys, re, json, subprocess, pathlib

if len(sys.argv) < 2:
    print("Usage: python3 release.py <version>")
    sys.exit(1)

version = sys.argv[1].lstrip('v')
tag = f"v{version}"

# 1. CHANGELOG-Eintrag extrahieren
changelog = pathlib.Path("CHANGELOG.md").read_text()
m = re.search(
    rf"## \[{re.escape(version)}\].*?(?=\n## \[|\Z)",
    changelog, re.DOTALL
)
if not m:
    print(f"ERROR: [{version}] nicht in CHANGELOG.md gefunden!")
    sys.exit(1)
body = m.group().strip()
print(f"Changelog-Eintrag: {len(body)} Zeichen")

# 2. PAT aus Umgebung
import os
pat = os.environ.get("GITHUB_PAT", "")
if not pat:
    print("ERROR: GITHUB_PAT Umgebungsvariable nicht gesetzt!")
    sys.exit(1)

headers = ["-H", f"Authorization: token {pat}", "-H", "Content-Type: application/json"]

# 3. Existierendes Release holen
r = subprocess.run(
    ["curl", "-s"] + headers +
    [f"https://api.github.com/repos/Xipher-Zero/debridpulse/releases/tags/{tag}"],
    capture_output=True, text=True
)
existing = json.loads(r.stdout)
release_id = existing.get("id")

payload = json.dumps({"tag_name": tag, "name": tag, "body": body})

if release_id:
    # Update
    r2 = subprocess.run(
        ["curl", "-s", "-X", "PATCH"] + headers +
        ["-d", payload, f"https://api.github.com/repos/Xipher-Zero/debridpulse/releases/{release_id}"],
        capture_output=True, text=True
    )
    resp = json.loads(r2.stdout)
    print(f"Release {tag} aktualisiert: {resp.get('html_url')}")
else:
    # Neu erstellen
    r2 = subprocess.run(
        ["curl", "-s", "-X", "POST"] + headers +
        ["-d", payload, "https://api.github.com/repos/Xipher-Zero/debridpulse/releases"],
        capture_output=True, text=True
    )
    resp = json.loads(r2.stdout)
    print(f"Release {tag} erstellt: {resp.get('html_url')}")
