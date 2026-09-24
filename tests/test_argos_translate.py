"""离线翻译（Argos Translate）接入测试。

不依赖本机真的装了 Argos：用假的 home + 打桩的 worker 测连线，
最后一个用例在真装好的机器上做一次真实翻译（没装就跳过）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easy_panel_app.integrations import argos  # noqa: E402


def make_home(folder: Path, pairs=("zh_en", "en_zh")) -> Path:
    """造一个假的 argos-translate 目录（venv python + 语言包目录）。"""

    python = folder / "venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"stub")
    for pair in pairs:
        package = folder / "data" / "argos-translate" / "packages" / f"translate-{pair}-1_9"
        package.mkdir(parents=True, exist_ok=True)
    return folder


ECHO_WORKER = (
    "import json, sys\n"
    "req = json.loads(sys.stdin.read() or '{}')\n"
    "out = ['EN:' + (item or '') for item in (req.get('texts') or [])]\n"
    "print('ARGOSJSON:' + json.dumps({'texts': out}, ensure_ascii=False))\n"
)


class ArgosDiscoveryTests(unittest.TestCase):
    def test_env_override_wins_and_missing_home_is_reported(self):
        with patch.object(argos, "DEFAULT_HOMES", (r"Z:\definitely-not-here",)):
            with patch.dict(os.environ, {argos.ENV_HOME: r"Y:\also-not-here"}, clear=False):
                self.assertEqual(Path(r"Y:\also-not-here"),
                                 argos.candidate_homes()[0])
                self.assertIsNone(argos.argos_home())
                info = argos.status()
        self.assertFalse(info["available"])
        self.assertIn(argos.ENV_HOME, info["reason"])

    def test_home_detected_from_env_variable(self):
        with tempfile.TemporaryDirectory() as folder:
            home = make_home(Path(folder))
            with patch.object(argos, "DEFAULT_HOMES", ()):
                with patch.dict(os.environ, {argos.ENV_HOME: str(home)}, clear=False):
                    self.assertEqual(home, argos.argos_home())
                    info = argos.status()
        self.assertTrue(info["available"])
        self.assertEqual(["en→zh", "zh→en"], sorted(info["pairs"]))
        self.assertTrue(info["python"].endswith("python.exe"))

    def test_missing_language_pack_is_explained(self):
        with tempfile.TemporaryDirectory() as folder:
            home = make_home(Path(folder), pairs=("en_de",))
            info = argos.status(home=home)
        self.assertFalse(info["available"])
        self.assertIn("zh→en", info["reason"])

    def test_installed_pairs_parsing(self):
        with tempfile.TemporaryDirectory() as folder:
            home = make_home(Path(folder), pairs=("zh_en", "en_zh"))
            packages = home / argos.PACKAGE_DIR
            (packages / "not-a-package").mkdir()
            pairs = argos.installed_pairs(home)
        self.assertEqual(
            [{"from": "en", "to": "zh", "version": "1.9"},
             {"from": "zh", "to": "en", "version": "1.9"}],
            sorted(pairs, key=lambda item: item["from"]),
        )


class ArgosTranslateTests(unittest.TestCase):
    def test_batch_translation_uses_one_subprocess_and_caches(self):
        with tempfile.TemporaryDirectory() as folder:
            home = make_home(Path(folder))
            calls = []

            def fake_worker(target, payload, timeout):
                calls.append(list(payload["texts"]))
                return ["EN:" + item for item in payload["texts"]]

            with patch.object(argos, "python_executable", return_value=Path(sys.executable)), \
                    patch.object(argos, "_run_worker", side_effect=fake_worker), \
                    patch.object(argos, "_cache", {}):
                first = argos.translate_texts(["蓝发", "白裙"], home=home)
                second = argos.translate_texts(["蓝发"], home=home)
        self.assertEqual(["EN:蓝发", "EN:白裙"], first)
        self.assertEqual(["EN:蓝发"], second)
        # 两条一次调用；第二次命中缓存，不再起子进程。
        self.assertEqual([["蓝发", "白裙"]], calls)

    def test_worker_parses_marker_line_from_real_subprocess(self):
        with tempfile.TemporaryDirectory() as folder:
            home = make_home(Path(folder))
            with patch.object(argos, "python_executable", return_value=Path(sys.executable)), \
                    patch.object(argos, "WORKER", ECHO_WORKER), \
                    patch.object(argos, "_cache", {}):
                out = argos.translate_texts(["a", "b"], home=home)
        self.assertEqual(["EN:a", "EN:b"], out)

    def test_worker_failure_reports_stderr_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            home = make_home(Path(folder))
            with patch.object(argos, "python_executable", return_value=Path(sys.executable)), \
                    patch.object(argos, "WORKER", "raise SystemExit('boom')\n"), \
                    patch.object(argos, "_cache", {}):
                with self.assertRaisesRegex(ValueError, "离线翻译执行失败"):
                    argos.translate_texts(["x"], home=home)

    def test_limits_and_empty_input(self):
        with tempfile.TemporaryDirectory() as folder:
            home = make_home(Path(folder))
            with self.assertRaisesRegex(ValueError, "请先填写"):
                argos.translate_texts([], home=home)
            with self.assertRaisesRegex(ValueError, "最多翻译"):
                argos.translate_texts(["x"] * (argos.MAX_TEXTS + 1), home=home)
            with self.assertRaisesRegex(ValueError, "过长"):
                argos.translate_texts(["x" * (argos.MAX_TEXT_CHARS + 1)], home=home)

    def test_language_pair_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            home = make_home(Path(folder), pairs=("en_zh",))
            with self.assertRaisesRegex(ValueError, "zh→en"):
                argos.translate_texts(["蓝发"], home=home)

    def test_en_to_zh_batch_for_prompt_explainer(self):
        """解析词条要的方向：英文 tag → 中文解释（en→zh 也是批量一次）。"""

        with tempfile.TemporaryDirectory() as folder:
            home = make_home(Path(folder))
            with patch.object(argos, "python_executable", return_value=Path(sys.executable)), \
                    patch.object(argos, "WORKER", ECHO_WORKER), \
                    patch.object(argos, "_cache", {}):
                out = argos.translate_texts(["bent over", "looking at viewer"],
                                            from_code="en", to_code="zh", home=home)
        self.assertEqual(["EN:bent over", "EN:looking at viewer"], out)

    def test_status_reports_pairs_for_both_directions(self):
        with tempfile.TemporaryDirectory() as folder:
            home = make_home(Path(folder))
            info = argos.status(home=home)
        self.assertTrue(info["available"])
        self.assertEqual(["en→zh", "zh→en"], sorted(info["pairs"]))

    def test_endpoint_shapes(self):
        with tempfile.TemporaryDirectory() as folder:
            home = make_home(Path(folder))
            with patch.object(argos, "python_executable", return_value=Path(sys.executable)), \
                    patch.object(argos, "WORKER", ECHO_WORKER), \
                    patch.object(argos, "_cache", {}), \
                    patch.dict(os.environ, {argos.ENV_HOME: str(home)}, clear=False):
                status_result = argos.argos_translate({"status": True})
                single = argos.argos_translate({"text": "蓝发成年女性"})
                batch = argos.argos_translate({"texts": ["蓝发", "白裙"]})
                with self.assertRaisesRegex(ValueError, "请先填写"):
                    argos.argos_translate({"text": "   "})
        self.assertTrue(status_result["status"]["available"])
        self.assertEqual("argos", single["engine"])
        self.assertEqual(["EN:蓝发成年女性"], [single["positive"]])
        self.assertEqual({"naturalLanguage": "EN:蓝发成年女性"}, single["sections"])
        self.assertEqual(["EN:蓝发", "EN:白裙"], batch["texts"])
        self.assertNotIn("positive", batch)


class ArgosWiringTests(unittest.TestCase):
    def test_backend_registers_the_endpoint(self):
        backend = (ROOT / "easy_panel.py").read_text(encoding="utf-8")
        self.assertIn("from easy_panel_app.integrations.argos import argos_translate", backend)
        self.assertIn('"/api/argos-translate"', backend)
        self.assertIn("argos_translate(data)", backend)

    def test_frontend_wiring(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("/assets/js/offline-translate.js?v=", page)
        self.assertIn("translateArgosOffline()", page)
        self.assertIn("translateArgosSections()", page)
        self.assertIn('id="argosHint"', page)
        self.assertIn('id="argosSectionHint"', page)
        # 每个带「清空 / 粘贴」的框也带一个「翻译」按钮（共 12 个）
        fields = re.findall(r'data-translate-field="([a-zA-Z]+)"', page)
        self.assertEqual(12, len(fields))
        for field in ("promptSubject", "promptPose", "promptScene", "negative"):
            self.assertIn(field, fields)
        for field in fields:
            self.assertIn(f"translateArgosField('{field}')", page)
        script = (ROOT / "web/assets/js/offline-translate.js").read_text(encoding="utf-8")
        for marker in ("/api/argos-translate", "easyPanelUndoOfflineTranslate",
                       "promptEditorChanged", "naturalLanguage", "global.translateArgosField"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)
        styles = (ROOT / "web/assets/css/panel.css").read_text(encoding="utf-8")
        self.assertIn(".prompt-section-translate{", styles)
        self.assertIn(".prompt-section-translate:hover", styles)

    def test_payload_copy_stays_byte_identical(self):
        for relative in ("easy_panel.py", "easy_panel_app/integrations/argos.py",
                         "index.html", "web/assets/js/offline-translate.js",
                         "web/assets/css/panel.css"):
            with self.subTest(relative=relative):
                self.assertEqual((ROOT / relative).read_bytes(),
                                 (ROOT / "installers" / "payload" / relative).read_bytes())


class ArgosRealMachineTests(unittest.TestCase):
    """本机真装好了 Argos 时跑一次真实翻译；没装就跳过。"""

    def test_real_translation_when_available(self):
        info = argos.status()
        if not info["available"]:
            self.skipTest("本机没有可用的 Argos：" + info["reason"])
        out = argos.translate_texts(["蓝发成年女性，白衬衫"])
        self.assertEqual(1, len(out))
        self.assertTrue(out[0].strip())
        self.assertFalse(any("\u4e00" <= char <= "\u9fff" for char in out[0]),
                         f"翻译结果仍是中文：{out[0]}")
        # 解析词条方向：英文 → 中文
        back = argos.translate_texts(["bent over"], from_code="en", to_code="zh")
        self.assertEqual(1, len(back))
        self.assertTrue(any("\u4e00" <= char <= "\u9fff" for char in back[0]),
                        f"en→zh 没有拿到中文：{back[0]}")


if __name__ == "__main__":
    unittest.main()
