#!/usr/bin/env python3
"""Install the portable Droppy Code decision runtime.

Packages the jev-mcp MCP server source, the offline Laya worker, the packs,
the frozen bookmark-topic question definitions and the npm manifests under
~/Library/Application Support/Droppy Code/decision-runtime (or --destination),
then installs production npm dependencies from the lockfile.

--download-laya additionally creates an isolated venv inside the runtime,
installs laya-mlx from its pinned commit, and downloads the pinned
aac6fef/laya-typed-decisions-mlx snapshot with huggingface_hub.

The installer writes only under the destination. It never touches app
installations, running sessions, host MCP registrations or the Keychain, and
never reads or writes credentials. It never copies node_modules, evaluation
corpora, telemetry, evidence, owner-specific paths or the FAILED
owner-override profile registry: a fresh empty version-1 registry is created
instead, and an existing registry is preserved on repeat installs.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAUNCHER_SOURCE = REPO / "scripts" / "decision-runtime-launch.mjs"
DEFAULT_DESTINATION = (
    Path.home() / "Library" / "Application Support" / "Droppy Code" / "decision-runtime"
)

WORKER = "tools/laya_worker.py"
QUESTION_FILES = (
    "config/technical-bookmark-topic-v1.json",
    "config/technical-bookmark-topic-v2.json",
)
MANIFESTS = ("package.json", "package-lock.json")
REGISTRY = "config/decision-profiles.json"
EMPTY_REGISTRY = {"version": 1, "profiles": {}}

NODE_MIN_MAJOR = 20
PYTHON_MIN = (3, 11)

# Pinned identities, matching the host evaluation environment record
# (laya-mlx direct_url.json and docs/laya-comparison-protocol.md).
LAYA_MLX_COMMIT = "fc1df62828a3fedf4d8229fdac1cbd85f1cdf337"
LAYA_MLX_SPEC = (
    "laya-mlx @ https://github.com/mizorewww/laya-mlx/archive/"
    f"{LAYA_MLX_COMMIT}.tar.gz"
)
MODEL_CHECKPOINT = "aac6fef/laya-typed-decisions-mlx"
MODEL_REVISION = "28416e78cb26a239a4eabaa2e084904ec5e6cacb"
MODEL_DIR = Path("models") / "models--aac6fef--laya-typed-decisions-mlx" / "snapshots" / MODEL_REVISION

IMPORT_RE = re.compile(r"""(?:from\s+|import\s+)["'](\.[^"']+)["']""")
SNAPSHOT_SNIPPET = (
    "import sys; from huggingface_hub import snapshot_download; "
    "snapshot_download(sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3])"
)
# Top-level staging entries merged as whole directories, never per file.
DIR_SWAPS = ("node_modules", "models")


def fail(message):
    print(f"install-decision-runtime: error: {message}", file=sys.stderr)
    sys.exit(1)


def run(argv, cwd=None):
    print(f"  $ {' '.join(str(a) for a in argv)}", flush=True)
    try:
        subprocess.run([str(a) for a in argv], cwd=cwd, check=True)
    except FileNotFoundError:
        fail(f"{argv[0]} is not on PATH")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"command failed with exit {exc.returncode}: {argv[0]}")


def write_atomic(path, text):
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def source_files():
    """The src/*.js files reachable from both server entry points."""
    src_root = (REPO / "src").resolve()
    seen, queue = set(), [src_root / "server.js", src_root / "laya-server.js"]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            text = current.read_text(encoding="utf-8")
        except OSError as exc:
            fail(f"cannot read required source {current}: {exc}")
        for match in IMPORT_RE.finditer(text):
            target = (current.parent / match.group(1)).resolve()
            if not (target == src_root or src_root in target.parents):
                fail(f"{current} imports {match.group(1)}, which resolves outside src/")
            queue.append(target)
    missing = [p for p in seen if not p.is_file()]
    if missing:
        fail("required source files missing: " + ", ".join(str(p) for p in missing))
    return sorted(str(p.relative_to(REPO)) for p in seen)


def check_node():
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        fail("Node >=20 and npm are required; install Node first — this installer changes nothing else.")
    out = subprocess.run([node, "-p", "process.versions.node"], capture_output=True, text=True)
    version = out.stdout.strip()
    try:
        major = int(version.split(".")[0])
    except ValueError:
        major = 0
    if out.returncode != 0 or major < NODE_MIN_MAJOR:
        fail(f"node {version or 'not found'} is too old; Node >={NODE_MIN_MAJOR} is required.")
    return npm


def find_python():
    for name in ("python3.14", "python3.13", "python3.12", "python3.11", "python3"):
        exe = shutil.which(name)
        if not exe:
            continue
        ok = subprocess.run(
            [exe, "-c", f"import sys; sys.exit(0 if sys.version_info >= {PYTHON_MIN} else 1)"],
            capture_output=True,
        ).returncode == 0
        if ok:
            return exe
    fail(
        "--download-laya needs a Python >=3.11 interpreter on PATH and found none. "
        "Install one yourself; this installer never installs Python, uv or Homebrew."
    )


def backup_or_mark(dest, path, backups):
    """Move an existing dest entry aside; record (backup, original) for restore."""
    if path.exists():
        bak = dest / f".backup-{os.getpid()}" / path.relative_to(dest)
        bak.parent.mkdir(parents=True, exist_ok=True)
        os.rename(path, bak)
        backups.append((bak, path))
    else:
        backups.append((None, path))


def provision_laya(dest, staging, backups):
    if sys.platform != "darwin" or platform.machine() != "arm64":
        fail("--download-laya requires macOS on Apple silicon; the pinned laya-mlx runtime is MLX-only.")
    python = find_python()
    dest.mkdir(parents=True, exist_ok=True)
    venv = dest / "venv"
    print(f"creating isolated venv at {venv} with {python}")
    backup_or_mark(dest, venv, backups)  # created at the final path: venv embeds absolute paths
    try:
        run([python, "-m", "venv", str(venv)])
        venv_py = venv / "bin" / "python"
        run([venv_py, "-m", "pip", "install", "--no-input", LAYA_MLX_SPEC])
    except Exception:
        shutil.rmtree(venv, ignore_errors=True)
        raise
    model_dir = staging / MODEL_DIR
    model_dir.mkdir(parents=True)
    print(f"downloading {MODEL_CHECKPOINT}@{MODEL_REVISION} into the runtime")
    run([venv_py, "-c", SNAPSHOT_SNIPPET, MODEL_CHECKPOINT, MODEL_REVISION, str(model_dir)])
    return {
        "python": str(venv_py),
        "modelPath": str(dest / MODEL_DIR),
        "checkpoint": MODEL_CHECKPOINT,
        "revision": MODEL_REVISION,
        "timeoutMs": 30000,
        "maxQueue": 8,
        "provenance": {
            "layaMlx": f"https://github.com/mizorewww/laya-mlx @ {LAYA_MLX_COMMIT}",
            "downloadedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }


def merge(staging, dest, backups):
    for name in DIR_SWAPS:
        src = staging / name
        if not src.exists():
            continue
        dst = dest / name
        backup_or_mark(dest, dst, backups)
        os.rename(src, dst)
    for entry in sorted(staging.iterdir()):
        if entry.name in DIR_SWAPS:
            continue  # moved above
        paths = entry.rglob("*") if entry.is_dir() else [entry]
        for path in sorted(paths):
            if not path.is_file():
                continue
            target = dest / path.relative_to(staging)
            target.parent.mkdir(parents=True, exist_ok=True)
            backup_or_mark(dest, target, backups)
            os.replace(path, target)


def write_runtime_config(dest, laya):
    path = dest / "runtime.json"
    if path.exists() and laya is None:
        return "preserved existing"
    write_atomic(path, json.dumps({"version": 1, "laya": laya}, indent=2) + "\n")
    return "wrote"


def ensure_registry(dest):
    path = dest / REGISTRY
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not (isinstance(data, dict) and data.get("version") == 1 and isinstance(data.get("profiles"), dict)):
                print("  note: existing profile registry has an unexpected shape; preserved unchanged")
        except (OSError, ValueError):
            print("  note: existing profile registry is not readable JSON; preserved unchanged")
        return "preserved existing"
    write_atomic(path, json.dumps(EMPTY_REGISTRY, indent=2) + "\n")
    return "created empty version-1"


def main():
    ap = argparse.ArgumentParser(
        description="Install the Droppy Code decision runtime (writes only under the destination)."
    )
    ap.add_argument(
        "--destination", type=Path, default=DEFAULT_DESTINATION,
        help=f"install root (default: {DEFAULT_DESTINATION})",
    )
    ap.add_argument(
        "--download-laya", action="store_true",
        help="provision the pinned local Laya-MLX runtime (Python >=3.11, Apple silicon, network)",
    )
    args = ap.parse_args()

    dest = args.destination.expanduser().resolve()
    if dest.exists() and not dest.is_dir():
        fail(f"destination exists and is not a directory: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    files = source_files()
    packs = sorted(str(p.relative_to(REPO)) for p in (REPO / "packs").glob("*.json"))
    if not packs:
        fail("calibration packs are required; packs/*.json is empty")
    files.extend(packs)
    for rel in (WORKER, *QUESTION_FILES, *MANIFESTS):
        if not (REPO / rel).is_file():
            fail(f"required source file missing: {rel}")
    if not LAUNCHER_SOURCE.is_file():
        fail(f"launcher source missing: {LAUNCHER_SOURCE}")
    check_node()

    staging = Path(tempfile.mkdtemp(prefix=f".{dest.name}.staging-", dir=dest.parent))
    backups = []  # (backup path or None, original path) restored on failure
    try:
        for rel in [*files, WORKER, *QUESTION_FILES, *MANIFESTS]:
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, target)
        shutil.copyfile(LAUNCHER_SOURCE, staging / "launch.mjs")
        os.chmod(staging / "launch.mjs", 0o755)

        print("installing production npm dependencies from the lockfile")
        run(["npm", "ci", "--omit=dev", "--no-audit", "--no-fund"], cwd=staging)

        laya = provision_laya(dest, staging, backups) if args.download_laya else None

        dest.mkdir(parents=True, exist_ok=True)
        if laya is not None or not (dest / "runtime.json").exists():
            write_runtime_config(staging, laya)
        if not (dest / REGISTRY).exists():
            ensure_registry(staging)
        merge(staging, dest, backups)

        backups.clear()
        shutil.rmtree(dest / f".backup-{os.getpid()}", ignore_errors=True)
    except BaseException as exc:
        for bak, orig in reversed(backups):
            try:
                if orig.is_dir() and not orig.is_symlink():
                    shutil.rmtree(orig)
                elif orig.exists() or orig.is_symlink():
                    orig.unlink()
                if bak is not None:
                    os.rename(bak, orig)
            except OSError:
                pass
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, (SystemExit, KeyboardInterrupt)):
            raise
        fail(f"{exc}; existing files were preserved or restored where possible.")
    shutil.rmtree(staging, ignore_errors=True)

    print(f"\nInstalled to {dest}")
    print(f"  Jev MCP entry point: node {dest / 'launch.mjs'} jev")
    print(f"  Laya MCP entry point: node {dest / 'launch.mjs'} laya")
    if laya:
        print(f"  local model: {MODEL_CHECKPOINT}@{MODEL_REVISION}")
    else:
        existing = None
        try:
            existing = json.loads((dest / "runtime.json").read_text(encoding="utf-8")).get("laya")
        except (OSError, ValueError):
            pass
        if existing:
            print("  local model: existing setup preserved")
        else:
            print("  local model: not configured — local inference requires re-running with --download-laya")


if __name__ == "__main__":
    main()
