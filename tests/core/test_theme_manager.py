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
    assert len(BUILTIN_THEMES) == 21


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
