"""Unit tests for Theme domain entities, built-in themes and ThemeManager."""

import pytest
from pygments.token import Token

from core.domain.defaults.themes import BUILTIN_THEMES
from core.domain.entities.theme import Theme
from widgets.app.theme_manager import ThemeManager


def test_theme_entity_creation():
    t = Theme(
        name="custom",
        label="Custom Theme",
        dark=True,
        primary="#111111",
        secondary="#222222",
        muted="#333333",
        subtle="#444444",
        tcss_vars={"bg-app": "#000000"},
        markdown_styles={"markdown.paragraph": "#ffffff"},
        syntax_tokens={Token.Keyword: "#ff0000"},
    )
    assert t.name == "custom"
    assert t.label == "Custom Theme"
    assert t.dark is True
    assert t.tcss_vars["bg-app"] == "#000000"
    assert t.markdown_styles["markdown.paragraph"] == "#ffffff"
    assert t.syntax_tokens[Token.Keyword] == "#ff0000"


def test_builtin_themes_presence():
    names = {t.name for t in BUILTIN_THEMES}
    assert "zinc" in names
    assert "charcoal" in names
    assert "catppuccin-mocha" in names
    assert "catppuccin-macchiato" in names
    assert "catppuccin-latte" in names
    assert "tokyo-night" in names
    assert "tokyo-night-storm" in names
    assert "rose-pine" in names
    assert "rose-pine-moon" in names
    assert "rose-pine-dawn" in names
    assert "github-dark" in names
    assert "github-dark-dimmed" in names
    assert "github-light" in names
    assert "kanagawa-wave" in names
    assert "kanagawa-dragon" in names
    assert "everforest" in names
    assert "ayu-dark" in names
    assert "ayu-mirage" in names
    assert "nord" in names
    assert "one-dark" in names
    assert "zinc-light" in names
    assert "gruvbox-material" in names
    assert "cyberdream" in names
    assert "vesper" in names
    assert "dracula" in names
    assert len(BUILTIN_THEMES) == 25


def test_theme_manager_registration_and_switching():
    tm = ThemeManager(default_theme="zinc")
    assert tm.current_theme.name == "zinc"

    # Switch theme
    charcoal = tm.set_theme("charcoal")
    assert charcoal.name == "charcoal"
    assert tm.current_theme.name == "charcoal"

    gh = tm.set_theme("github-dark")
    assert gh.name == "github-dark"
    assert tm.current_theme.name == "github-dark"

    # Switch to unknown theme raises ValueError
    with pytest.raises(ValueError, match="Unknown theme"):
        tm.set_theme("nonexistent-theme-xyz")


def test_theme_manager_listeners():
    tm = ThemeManager()
    events = []

    def on_theme_change(theme: Theme):
        events.append(theme.name)

    tm.add_listener(on_theme_change)
    tm.set_theme("nord")
    tm.set_theme("tokyo-night")

    assert events == ["nord", "tokyo-night"]

    tm.remove_listener(on_theme_change)
    tm.set_theme("zinc")
    assert events == ["nord", "tokyo-night"]


def test_theme_manager_textual_theme_conversion():
    tm = ThemeManager()
    tt = tm.get_textual_theme("zinc")
    assert tt.name == "zinc"
    assert tt.background is not None
    assert tt.surface is not None
    assert "bg-app" in tt.variables

    all_tt = tm.get_all_textual_themes()
    assert len(all_tt) == len(BUILTIN_THEMES)


def test_theme_persistence(tmp_path, monkeypatch):
    cfg_file = str(tmp_path / "config.json")
    monkeypatch.setattr("core.infrastructure.platform.paths.CONFIG_FILE", cfg_file)

    from core.infrastructure.config.config_helpers import load_theme_config, save_theme_config

    assert load_theme_config(cfg_file) is None

    save_theme_config("charcoal", cfg_file)
    assert load_theme_config(cfg_file) == "charcoal"

    save_theme_config("nord", cfg_file)
    assert load_theme_config(cfg_file) == "nord"


def test_theme_serialization_and_validation():
    # Valid serialization & deserialization
    data = {
        "name": "synthwave",
        "label": "Synthwave 84",
        "dark": True,
        "primary": "#ff7edb",
        "secondary": "#36f9f6",
        "muted": "#848bbd",
        "subtle": "#fe4450",
        "tcss_vars": {"bg-app": "#262335", "bg-surface": "#241b2f"},
        "markdown_styles": {"markdown.paragraph": "#f92aad"},
        "syntax_tokens": {"Token.Keyword": "#fe4450", "Name.Function": "#36f9f6"},
    }
    theme = Theme.from_dict(data)
    assert theme.name == "synthwave"
    assert theme.label == "Synthwave 84"
    assert theme.syntax_tokens[Token.Keyword] == "#fe4450"
    assert theme.syntax_tokens[Token.Name.Function] == "#36f9f6"

    serialized = theme.to_dict()
    assert serialized["name"] == "synthwave"
    assert serialized["primary"] == "#ff7edb"

    # Validation errors
    with pytest.raises(ValueError, match="Theme data must be a dictionary"):
        Theme.from_dict("invalid")  # type: ignore

    with pytest.raises(ValueError, match="Theme 'name' is required"):
        Theme.from_dict({"label": "No Name"})

    with pytest.raises(ValueError, match="Theme name must be a non-empty string"):
        Theme(name="", label="Empty")

    with pytest.raises(ValueError, match="Theme label must be a non-empty string"):
        Theme(name="theme", label="")


def test_theme_manager_load_user_themes(tmp_path):
    themes_dir = tmp_path / "themes"
    themes_dir.mkdir()

    custom_json = themes_dir / "custom-matrix.json"
    custom_json.write_text(
        '{\n'
        '  "name": "matrix",\n'
        '  "label": "Matrix Green",\n'
        '  "dark": true,\n'
        '  "primary": "#00ff00",\n'
        '  "tcss_vars": {"bg-app": "#000000"}\n'
        '}'
    )

    invalid_json = themes_dir / "invalid.json"
    invalid_json.write_text('{"invalid": true}')

    tm = ThemeManager(load_config=False, custom_themes_dir=themes_dir)
    assert tm.get("matrix") is not None
    assert tm.get("matrix").label == "Matrix Green"

    # Check non-existent directory handled gracefully
    tm_empty = ThemeManager(load_config=False, custom_themes_dir=tmp_path / "nonexistent")
    assert len(tm_empty.list_themes()) == len(BUILTIN_THEMES)


def test_theme_manager_singleton_and_reset():
    ThemeManager.reset_instance()
    inst1 = ThemeManager.get_instance()
    inst2 = ThemeManager.get_instance()
    assert inst1 is inst2

    ThemeManager.reset_instance()
    inst3 = ThemeManager.get_instance()
    assert inst3 is not inst1

