#!/usr/bin/env python3
"""Generate catalog.json for arkady-marketplace from this repo's releases.

For every release tagged <plugin_name>-v<version>, reads that plugin's
manifest.yaml as of that exact tag (not HEAD, which may already be ahead of
the last release) and pairs it with the signed .arkadypkg asset actually
uploaded to that release. Only the newest release per plugin is kept.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import requests
import yaml

REPO = "reraaaaa/arkady_plugins"
CATEGORY_DIRS = {"models": "model", "tools": "tool"}
TAG_RE = re.compile(r"^(?P<name>.+)-v(?P<version>\d.*)$")


def list_releases() -> list[dict]:
    releases: list[dict] = []
    page = 1
    session = requests.Session()
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    while True:
        response = session.get(
            f"https://api.github.com/repos/{REPO}/releases",
            params={"per_page": 100, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        releases.extend(batch)
        page += 1

    return releases


def find_manifest_dir(tag: str, name: str) -> str | None:
    for category_dir in CATEGORY_DIRS:
        path = f"{category_dir}/{name}"
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{tag}:{path}/manifest.yaml"],
            capture_output=True,
        )
        if result.returncode == 0:
            return category_dir
    return None


def read_manifest(tag: str, category_dir: str, name: str) -> dict:
    result = subprocess.run(
        ["git", "show", f"{tag}:{category_dir}/{name}/manifest.yaml"],
        capture_output=True,
        check=True,
        text=True,
    )
    return yaml.safe_load(result.stdout)


def normalize_i18n(value) -> dict[str, str]:
    if isinstance(value, dict):
        return {k: str(v) for k, v in value.items()}
    if isinstance(value, str):
        return {"en_US": value}
    return {}


def build_entry(release: dict, name: str, version: str) -> dict | None:
    tag = release["tag_name"]
    category_dir = find_manifest_dir(tag, name)
    if category_dir is None:
        print(f"::warning::No manifest.yaml found for {tag} under models/ or tools/, skipping", file=sys.stderr)
        return None

    manifest = read_manifest(tag, category_dir, name)

    asset = next((a for a in release.get("assets", []) if a["name"].endswith(".signed.arkadypkg")), None)
    if asset is None:
        print(f"::warning::No signed .arkadypkg asset on release {tag}, skipping", file=sys.stderr)
        return None

    return {
        "name": manifest["name"],
        "org": manifest["author"],
        "category": CATEGORY_DIRS[category_dir],
        "version": version,
        "label": normalize_i18n(manifest.get("label")),
        "description": normalize_i18n(manifest.get("description")),
        "icon": f"https://raw.githubusercontent.com/{REPO}/{tag}/{category_dir}/{name}/_assets/{manifest['icon']}",
        "releaseTag": tag,
        "assetName": asset["name"],
        "repository": f"https://github.com/{REPO}",
        "resource": manifest.get("resource", {}),
    }


def main() -> None:
    releases = list_releases()
    seen_names: set[str] = set()
    plugins: list[dict] = []

    for release in releases:
        match = TAG_RE.match(release["tag_name"])
        if not match:
            continue
        name = match.group("name")
        if name in seen_names:
            continue  # already have the newer release for this plugin
        seen_names.add(name)

        entry = build_entry(release, name, match.group("version"))
        if entry is not None:
            plugins.append(entry)

    plugins.sort(key=lambda p: (p["category"], p["name"]))
    catalog = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "plugins": plugins,
    }

    with open("catalog.json", "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote catalog.json with {len(plugins)} plugins.")


if __name__ == "__main__":
    main()
