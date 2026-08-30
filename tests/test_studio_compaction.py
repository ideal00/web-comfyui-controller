import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class StudioCompactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "web/assets/js/panel.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "web/assets/css/panel.css").read_text(encoding="utf-8")

    def test_tag_search_lives_inside_prompt_composer(self):
        prompt_start = self.html.index('id="promptComposer"')
        prompt_end = self.html.index("</section>", prompt_start)
        self.assertGreater(self.html.index('id="tagSearch"'), prompt_start)
        self.assertLess(self.html.index('id="tagSearch"'), prompt_end)
        self.assertIn('class="prompt-tag-search"', self.html)
        self.assertIn('id="promptSectionGrid"', self.html)
        self.assertIn("function setPromptSectionTab(tab)", self.js)
        self.assertIn(".prompt-section-grid.prompt-tab-character", self.css)

    def test_prompt_and_generation_settings_are_separate_views(self):
        for marker in (
            'id="studioPromptTab"',
            'id="studioSettingsTab"',
            'id="studioPromptView"',
            'id="studioSettingsView"',
        ):
            self.assertIn(marker, self.html)
        self.assertIn("function setStudioCreationTab(tab,shouldFocus=false)", self.js)
        self.assertIn("function initStudioCreationTabs()", self.js)
        self.assertIn("initStudioToolDrawer();initStudioCreationTabs();", self.js)
        self.assertIn(".studio-create-tabs{display:grid", self.css)
        self.assertIn(".studio-creation-view[hidden]{display:none!important}", self.css)

    def test_uncommon_tools_move_into_collapsible_side_drawer(self):
        self.assertIn('id="studioToolDrawer"', self.html)
        self.assertIn('id="studioToolDrawerContent"', self.html)
        self.assertIn('class="studio-tool-drawer-backdrop" onclick="toggleStudioToolDrawer(false)"', self.html)
        self.assertIn("function initStudioToolDrawer()", self.js)
        for control in ("route1Panel", "poseMemo", "regionsEnabled", "colorEnabled", "img2imgEnabled"):
            self.assertIn(control, self.js)
        self.assertIn(".studio-tool-drawer.open", self.css)
        self.assertIn("left:0;bottom:0;z-index:85;width:0", self.css)
        self.assertIn("transform:translateX(-100%)", self.css)
        self.assertIn(".studio-tool-drawer.open .studio-tool-drawer-backdrop{display:block}", self.css)

    def test_advanced_tools_button_shares_quick_jump_column(self):
        nav_start = self.html.index('class="panel-quick-jumps"')
        nav_end = self.html.index("</nav>", nav_start)
        toggle = self.html.index('id="studioToolDrawerToggle"')
        self.assertGreater(toggle, nav_start)
        self.assertLess(toggle, nav_end)
        self.assertIn(".panel-quick-jumps .studio-tool-drawer-toggle", self.css)

    def test_lora_memo_uses_large_dialog_and_active_row(self):
        self.assertIn('id="loraMemoDialog"', self.html)
        self.assertIn('id="memoActiveLora"', self.html)
        self.assertIn("dialog.showModal()", self.js)
        self.assertIn("memo-active", self.js)
        self.assertIn("selectLoraNote(select.value,select)", self.js)
        self.assertIn(".lora-memo-dialog", self.css)

    def test_lora_editor_keeps_sidecar_txt_visible_beside_scrollable_form(self):
        self.assertIn("memoSidecarReferenceHtml()", self.js)
        self.assertIn("copyLoraSidecarText(this)", self.js)
        self.assertIn('class="memo-editor-layout"', self.js)
        self.assertIn('class="memo-edit-scroll"', self.js)
        self.assertIn('class="memo-sidecar-reference"', self.js)
        self.assertIn(".lora-memo-dialog .memo-editor-layout{display:grid", self.css)
        self.assertIn(".lora-memo-dialog .memo-edit-scroll{min-width:0;min-height:0", self.css)
        self.assertIn(".memo-sidecar-reference pre{flex:1", self.css)

    def test_lora_name_uses_full_row_and_hover_title(self):
        self.assertIn(".studio-lora .lora-select{grid-column:1/-1;grid-row:1}", self.css)
        self.assertIn("select.title=name||'请选择 LoRA'", self.js)
        self.assertIn("select.title=select.value||'请选择 LoRA'", self.js)


if __name__ == "__main__":
    unittest.main()
