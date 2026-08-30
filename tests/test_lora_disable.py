import unittest
from pathlib import Path


class LoraDisableTests(unittest.TestCase):
    def test_loaded_lora_can_be_disabled_without_being_removed(self):
        script = Path("web/assets/js/panel.js").read_text(encoding="utf-8")
        css = Path("web/assets/css/panel.css").read_text(encoding="utf-8")

        for marker in (
            "function allLoraState",
            "enabled:row.dataset.enabled!=='false'",
            "function updateLoraEnabledUi",
            "function toggleLoraEnabled",
            "enabledToggle.className='lora-enabled-toggle'",
            "row.append(select,strength,controls,enabledToggle,favorite,remove)",
            "addLora(item.name,String(item.weight??'0.70'),item.enabled!==false)",
            "allLoraState().filter(item=>item.enabled)",
        ):
            self.assertIn(marker, script)
        self.assertIn(".studio-lora .lora-row.lora-disabled", css)
        self.assertIn(".studio-lora .lora-enabled-toggle", css)
        self.assertIn("不会参与生成", script)


if __name__ == "__main__":
    unittest.main()
