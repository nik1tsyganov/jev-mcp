"""Catalog snapshots, selectable freeze files, verification and drift reports.

Canonical catalogs are copied into frozen-inputs/ and only those copies are read
by the v2 guard. A freeze file is named by the caller (for example
FROZEN-v2-protocol.json before dev runs, FROZEN-v2.json before held-out runs);
it is written once and never overwritten.
"""
import json
from pathlib import Path
import shutil

from .common import FROZEN_INPUTS, ROOT, read_json, rel, sha256, utc_now, write_json

INTEGRATION = Path.home() / ".local/scratch/droppy-oracle-cli-integration"
LIVE_SOURCES = {
    "routing.json": Path.home() / "Documents/Agent-Vault/Skills/mix-mode/references/routing.json",
    "conclave-seats.json": Path.home() / "Documents/Agent-Vault/Skills/conclave/references/conclave-seats.json",
    "codex-models_cache.json": Path.home() / ".codex/models_cache.json",
    # Product authority inputs of the integrated Oracle CLI (merge 329ecdea), copied, never edited.
    "dispatch-matrix.json": Path.home() / "src/conclave/contracts/dispatch-matrix.json",
    "conclave-seat-catalog-v1.json": INTEGRATION / "DroppyCode/Resources/Oracle/conclave-seat-catalog-v1.json",
    "oracle_snapshot.py": INTEGRATION / "build.noindex/integration-oracle/adapter/snapshot.py",
}
CATALOG_MANIFEST = "CATALOGS.json"


def snapshot_catalogs(dest=FROZEN_INPUTS, sources=None, overwrite=False):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / CATALOG_MANIFEST).exists() and not overwrite:
        raise ValueError("catalog snapshot already exists; snapshots are not replaced silently")
    manifest = {"taken_at": utc_now(), "files": {}}
    for name, source in (sources or LIVE_SOURCES).items():
        source = Path(source)
        if not source.is_file():
            raise ValueError(f"canonical catalog missing: {name}")
        shutil.copyfile(source, dest / name)
        manifest["files"][name] = {"source": rel(source), "sha256": sha256(dest / name)}
    cache = read_json(dest / "codex-models_cache.json")
    manifest["files"]["codex-models_cache.json"]["fetched_at"] = cache.get("fetched_at")
    manifest["files"]["routing.json"]["updated"] = (read_json(dest / "routing.json").get("_meta") or {}).get("updated")
    write_json(dest / CATALOG_MANIFEST, manifest)
    return manifest


def verify_snapshot(dest=FROZEN_INPUTS):
    dest = Path(dest)
    manifest = read_json(dest / CATALOG_MANIFEST)
    for name, entry in manifest["files"].items():
        if sha256(dest / name) != entry["sha256"]:
            raise ValueError(f"catalog snapshot changed: {name}")
    return manifest


def _effort_rows(routing, cache):
    rows = {}
    for row in cache.get("models", []):
        slug = row.get("slug") or row.get("id")
        rows[("codex-cache", slug)] = sorted(level.get("effort") for level in row.get("supported_reasoning_levels", []))
    for model, efforts in routing.get("efforts", {}).get("codexByModel", {}).items():
        rows[("routing.codexByModel", model)] = sorted(efforts)
    for key in ("claudeModels", "codexModels", "geminiModels"):
        rows[("routing." + key, "*")] = sorted(routing.get(key, []))
    rows[("routing.efforts.claude", "*")] = sorted(routing.get("efforts", {}).get("claude", []))
    return rows


def drift(dest=FROZEN_INPUTS, sources=None):
    """Differences between the frozen copies and the live canonical files (report only)."""
    dest, sources = Path(dest), sources or LIVE_SOURCES
    out = {"checked_at": utc_now(), "files": {}, "rows": []}
    for name, source in sources.items():
        live = Path(source)
        out["files"][name] = {"frozen": sha256(dest / name),
                              "live": sha256(live) if live.is_file() else None}
        out["files"][name]["changed"] = out["files"][name]["frozen"] != out["files"][name]["live"]
    frozen_rows = _effort_rows(read_json(dest / "routing.json"), read_json(dest / "codex-models_cache.json"))
    live_routing, live_cache = Path(sources["routing.json"]), Path(sources["codex-models_cache.json"])
    if live_routing.is_file() and live_cache.is_file():
        live_rows = _effort_rows(read_json(live_routing), read_json(live_cache))
        for key in sorted(set(frozen_rows) | set(live_rows), key=str):
            if frozen_rows.get(key) != live_rows.get(key):
                out["rows"].append({"source": key[0], "model": key[1],
                                    "frozen": frozen_rows.get(key), "live": live_rows.get(key)})
    return out


def freeze(name, paths, extra=None, root=ROOT):
    """Write freeze file `name` (once) with SHA-256 of every path."""
    target = Path(root) / name
    if not name.startswith("FROZEN-") or not name.endswith(".json"):
        raise ValueError("freeze files are named FROZEN-*.json")
    hashes = {}
    for path in sorted({Path(p).resolve() for p in paths}):
        if not path.is_file():
            raise ValueError(f"freeze input missing: {path}")
        hashes[rel(path, root)] = sha256(path)
    record = {"name": name, "frozen_at": utc_now(), "hashes": hashes, **(extra or {})}
    with target.open("x", encoding="utf-8") as stream:  # never overwrite
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return record


def verify(name, root=ROOT):
    root = Path(root)
    if not (root / name).is_file():
        raise ValueError(f"freeze file missing: {name}")
    record = read_json(root / name)
    for key, expected in record["hashes"].items():
        path = (root / key) if not key.startswith("~/") else Path.home() / key[2:]
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"frozen input changed: {key}")
    return record


def snapshot_helper(app_dir, extra_files, dest_root, version):
    """Copy a whole helper bundle plus catalogs/client manifest into dest_root/version, record every
    file's SHA-256, and make the copy read-only. Never overwrites; run only on an accepted final build."""
    import os
    import stat
    app_dir, dest = Path(app_dir), Path(dest_root) / version
    if dest.exists():
        raise ValueError(f"helper snapshot {version} already exists")
    if not app_dir.is_dir():
        raise ValueError(f"helper bundle missing: {app_dir}")
    shutil.copytree(app_dir, dest / app_dir.name, symlinks=True)
    for item in extra_files:
        item = Path(item)
        if not item.is_file():
            raise ValueError(f"snapshot input missing: {item}")
        target = dest / "extra" / item.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
    files = {str(path.relative_to(dest)): sha256(path) for path in sorted(dest.rglob("*"))
             if path.is_file() and not path.is_symlink()}
    manifest = {"version": version, "taken_at": utc_now(), "source_bundle": rel(app_dir),
                "extra_sources": [rel(Path(x)) for x in extra_files], "files": files}
    write_json(dest / "HELPER-MANIFEST.json", manifest)
    for path in sorted(dest.rglob("*"), reverse=True):
        if not path.is_symlink():
            mode = path.stat().st_mode
            path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    os.chmod(dest, os.stat(dest).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    return manifest


def verify_helper_snapshot(dest):
    dest = Path(dest)
    manifest = read_json(dest / "HELPER-MANIFEST.json")
    for name, expected in manifest["files"].items():
        if sha256(dest / name) != expected:
            raise ValueError(f"helper snapshot changed: {name}")
    if any(path.stat().st_mode & 0o222 for path in dest.rglob("*") if path.is_file() and not path.is_symlink()):
        raise ValueError("helper snapshot is writable")
    return manifest
