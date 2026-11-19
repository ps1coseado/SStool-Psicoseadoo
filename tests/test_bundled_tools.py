"""Herramientas incluidas en bundled_tools/ (instalacion local verificada, sin enlace de descarga)."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import launcher
from core.data import CATEGORIES
from core.i18n import tool_description
from core.tool_info import tool_info, to_english

EXPECTED = {
    # nombre: (categoria, archivo, es_script)
    "Eventvwr Parser": ("nirsoft", "EventvwrParser.exe", False),
    "PsicoChecker": ("scripts", "PsicoChecker.ps1", True),
    "jd-gui": ("nirsoft", "jd-gui.exe", False),
    "DiskPart+": ("nirsoft", "DiskPart+.exe", False),
    "MFT-HardLink": ("orbdiff", "MFT-HardLink.exe", False),
    "MFTParser": ("orbdiff", "MFTParser.exe", False),
    "ReplaceParser": ("redlotus", "ReplaceParser.exe", False),
    "Pca-Files": ("scripts", "Pca-Files.ps1", True),
    "LogFileParser": ("nirsoft", "LogFileParser.exe", False),
    "ShellSearch": ("scripts", "ShellSearch.ps1", True),
    "CommonDirectories": ("scripts", "CommonDirectories.ps1", True),
}


def _bundled():
    return {t["name"]: (c["id"], t) for c in CATEGORIES for t in c["tools"] if t.get("bundled")}


class CatalogueTests(unittest.TestCase):
    def test_all_requested_buttons_exist_in_the_requested_category(self):
        found = _bundled()
        self.assertEqual(set(found), set(EXPECTED))
        for name, (category, filename, is_script) in EXPECTED.items():
            cid, tool = found[name]
            self.assertEqual(cid, category, name)
            self.assertEqual(tool["bundled"], filename)
            self.assertEqual(tool["path"], filename)
            self.assertTrue(tool["run_as_admin"], name)
            self.assertEqual(tool.get("runner") == "powershell", is_script, name)
            self.assertEqual(tool["storage_category"], category)
            self.assertFalse(tool.get("url"), "no se inventan URLs de descarga")

    def test_ids_and_names_stay_unique(self):
        ids = [t.get("id") for c in CATEGORIES for t in c["tools"] if t.get("id")]
        self.assertEqual(len(ids), len(set(ids)))
        names = [t["name"] for c in CATEGORIES for t in c["tools"]]
        self.assertEqual(len(names), len(set(names)))

    def test_bundled_files_match_their_declared_sha256(self):
        for name, (_, tool) in _bundled().items():
            path = launcher.bundled_tool_path(tool["bundled"])
            self.assertTrue(os.path.isfile(path), path)
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), tool["sha256"], name)

    def test_payloads_are_valid_for_their_runner(self):
        for name, (_, tool) in _bundled().items():
            path = launcher.bundled_tool_path(tool["bundled"])
            raw = Path(path).read_bytes()
            if tool.get("runner") == "powershell":
                text = raw.decode("utf-8-sig")  # UTF-8 valido
                if any(ord(ch) > 127 for ch in text):
                    # Windows PowerShell 5.1 lee como ANSI los .ps1 sin BOM y rompe las comillas.
                    self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), f"{name} necesita BOM UTF-8")
            else:
                self.assertEqual(raw[:2], b"MZ", name)

    def test_every_new_button_has_both_languages(self):
        for name, (_, tool) in _bundled().items():
            en, es = tool_description(tool, "en"), tool_description(tool, "es")
            self.assertTrue(en and es, name)
            self.assertNotEqual(en, es, f"{name} sin traduccion al espanol")

    def test_requested_texts(self):
        tools = {n: t for n, (_, t) in _bundled().items()}
        self.assertEqual(tools["Eventvwr Parser"]["desc"], (
            "SS tool that reads the Windows events and shows them all together in one place, so you don't "
            "have to keep opening Event Viewer and filtering log by log like a maniac."))
        self.assertTrue(tool_description(tools["Eventvwr Parser"], "es").startswith("Herramienta para SS"))
        self.assertEqual(tools["jd-gui"]["desc"], "Java decompiler")
        self.assertIn("$UsnJrnl", tools["LogFileParser"]["desc"])

    def test_other_tools_keep_eventvwr_and_consolehosthistory_last(self):
        other = next(c for c in CATEGORIES if c["id"] == "nirsoft")
        names = [t["name"] for t in other["tools"]]
        self.assertEqual(names[names.index("Siege") + 1:], ["Eventvwr", "ConsoleHostHistory"])

    def test_tool_info_labels_bundled_tools_as_sstool(self):
        info = tool_info(_bundled()["jd-gui"][1])
        self.assertEqual(info["source"], "SSTool+")
        self.assertIsNone(info["link"])

    def test_missing_bundle_error_is_translated(self):
        message = "el archivo incluido con SSTool+ no se encontro; vuelve a descargar o reinstalar SSTool+"
        self.assertIn("was not found", to_english(message))


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "tools"
        patcher = patch("core.launcher.tools_root_directory", return_value=str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _launch(self, name, **kwargs):
        category, tool = _bundled()[name]
        runs = []
        with patch("core.launcher._run_tool", side_effect=lambda path, t=None: runs.append(path) or False):
            ok = launcher.launch_tool(tool["storage_category"], tool, on_error=kwargs.get("errors", []).append)
        return ok, runs, tool

    def test_first_launch_installs_a_verified_copy_and_runs_it(self):
        ok, runs, tool = self._launch("jd-gui")
        installed = self.root / "nirsoft" / "jd-gui.exe"
        self.assertTrue(ok)
        self.assertEqual(runs, [str(installed)])
        self.assertEqual(hashlib.sha256(installed.read_bytes()).hexdigest(), tool["sha256"])
        self.assertTrue(Path(str(installed) + launcher.INSTALL_MARKER_SUFFIX).is_file())

    def test_second_launch_reuses_the_install(self):
        self._launch("ReplaceParser")
        with patch("core.launcher._install_bundled") as install:
            ok, runs, _ = self._launch("ReplaceParser")
        self.assertTrue(ok)
        install.assert_not_called()
        self.assertEqual(len(runs), 1)

    def test_tampered_install_is_replaced_from_the_bundle(self):
        self._launch("MFT-HardLink")
        installed = self.root / "orbdiff" / "MFT-HardLink.exe"
        installed.write_bytes(b"MZ-tampered")
        ok, _, tool = self._launch("MFT-HardLink")
        self.assertTrue(ok)
        self.assertEqual(hashlib.sha256(installed.read_bytes()).hexdigest(), tool["sha256"])

    def test_powershell_script_installs_with_its_bom(self):
        ok, runs, tool = self._launch("CommonDirectories")
        self.assertTrue(ok)
        self.assertTrue((self.root / "scripts" / "CommonDirectories.ps1").read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_modified_bundle_is_refused_and_nothing_runs(self):
        category, tool = _bundled()["Eventvwr Parser"]
        fake = Path(self.tmp.name) / "EventvwrParser.exe"
        fake.write_bytes(b"MZ" + b"\x00" * 64)
        errors = []
        with patch("core.launcher.bundled_tool_path", return_value=str(fake)), \
                patch("core.launcher._run_tool") as run:
            ok = launcher.launch_tool(tool["storage_category"], tool, on_error=errors.append)
        self.assertFalse(ok)
        run.assert_not_called()
        self.assertIn("SHA-256", errors[0])
        self.assertFalse((self.root / "nirsoft" / "EventvwrParser.exe").exists())

    def test_missing_bundle_reports_a_clear_error(self):
        category, tool = _bundled()["jd-gui"]
        errors = []
        with patch("core.launcher.bundled_tool_path", return_value=str(Path(self.tmp.name) / "nope.exe")):
            ok = launcher.launch_tool(tool["storage_category"], tool, on_error=errors.append)
        self.assertFalse(ok)
        self.assertIn("reinstalar SSTool+", errors[0])


class ElevatedScriptTests(unittest.TestCase):
    @patch("core.launcher.sys.platform", "win32")
    @patch("core.launcher._powershell_executable", return_value="powershell")
    @patch("core.launcher._cmd_executable", return_value="C:\\Windows\\System32\\cmd.exe")
    @patch("core.launcher._run_command_elevated")
    def test_admin_ps1_keeps_quotes_for_paths_with_spaces(self, elevated, *_):
        tool = {"runner": "powershell", "run_as_admin": True}
        path = "C:\\Users\\John Doe\\Downloads\\tools\\scripts\\ShellSearch.ps1"
        self.assertTrue(launcher._run_tool(path, tool))
        self.assertEqual(elevated.call_args.args[0], "C:\\Windows\\System32\\cmd.exe")
        self.assertEqual(
            elevated.call_args.kwargs["raw_arguments"],
            '/d /k "powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + path + '""',
        )

    @patch("core.launcher.sys.platform", "win32")
    @patch("core.launcher._powershell_executable", return_value="powershell")
    @patch("core.launcher._cmd_executable", return_value="cmd.exe")
    @patch("core.launcher._run_command_elevated")
    def test_admin_ps1_without_spaces(self, elevated, *_):
        tool = {"runner": "powershell", "run_as_admin": True}
        launcher._run_tool("C:\\Users\\psico\\Downloads\\tools\\scripts\\Pca-Files.ps1", tool)
        self.assertEqual(
            elevated.call_args.kwargs["raw_arguments"],
            '/d /k "powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File '
            'C:\\Users\\psico\\Downloads\\tools\\scripts\\Pca-Files.ps1"',
        )


if __name__ == "__main__":
    unittest.main()
