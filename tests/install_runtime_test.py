"""Installer update safety, without package downloads or model execution."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("installer", Path(__file__).resolve().parents[1] / "scripts/install-decision-runtime.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_source_files_traverses_both_entry_points(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder).resolve()
            src = repo / "src"
            src.mkdir()
            (src / "server.js").write_text('import "./jev-client.js";\n')
            (src / "laya-server.js").write_text('import "./laya-service.js";\n')
            (src / "jev-client.js").write_text('import "./questions.js";\n')
            (src / "laya-service.js").write_text('import "./questions.js";\n')
            (src / "questions.js").write_text("export {};\n")
            with patch.object(installer, "REPO", repo):
                self.assertEqual(installer.source_files(), [
                    "src/jev-client.js", "src/laya-server.js", "src/laya-service.js",
                    "src/questions.js", "src/server.js",
                ])

    def install(self, dest):
        def fake_npm(argv, cwd=None):
            (Path(cwd) / "node_modules").mkdir()
        with patch.object(sys, "argv", ["installer", "--destination", str(dest)]), patch.object(installer, "check_node"), patch.object(installer, "run", fake_npm), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            installer.main()

    def test_fresh_install_has_packs_and_no_personal_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder).resolve() / "runtime"
            self.install(dest)
            for entry in ("server.js", "laya-server.js"):
                self.assertTrue((dest / "src" / entry).is_file())
            self.assertEqual(
                [name for name in installer.source_files() if name in ("src/server.js", "src/laya-server.js")],
                ["src/laya-server.js", "src/server.js"],
            )
            self.assertEqual(sorted(p.name for p in (dest / "packs").glob("*.json")), sorted(p.name for p in (installer.REPO / "packs").glob("*.json")))
            self.assertEqual(json.loads((dest / installer.REGISTRY).read_text()), installer.EMPTY_REGISTRY)
            self.assertFalse((dest / "docs/evidence").exists())
            registry = '{"version":1,"profiles":{"personal":{"enabled":false}}}'
            (dest / installer.REGISTRY).write_text(registry)
            self.install(dest)
            self.assertEqual((dest / installer.REGISTRY).read_text(), registry)

    def test_failed_update_restores_files_and_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder).resolve() / "runtime"
            self.install(dest)
            (dest / "launch.mjs").write_text("previous launcher")
            (dest / "node_modules/sentinel").write_text("previous dependency")
            before = {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
            original_replace = installer.os.replace
            failed = False
            def fail_once(src, target):
                nonlocal failed
                if Path(target) == dest / "src/client.js" and not failed:
                    failed = True
                    raise OSError("injected interrupted update")
                return original_replace(src, target)
            with patch.object(installer.os, "replace", fail_once):
                with self.assertRaises(SystemExit):
                    self.install(dest)
            self.assertTrue(failed)
            for path, content in before.items():
                self.assertEqual((dest / path).read_bytes(), content, str(path))


if __name__ == "__main__":
    unittest.main()
