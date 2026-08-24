"""Keybinding aliases and layout normalization for terminal and cross-layout compatibility.

Provides Cyrillic (RU / ЙЦУКЕН) aliases for Ctrl/Cmd combos and Textual screen bindings
to ensure hotkeys work regardless of active keyboard layout.
"""

from typing import Sequence

# QWERTY latin character to Russian (йцукен) mapping
QWERTY_TO_RU: dict[str, str] = {
    "q": "й", "w": "ц", "e": "у", "r": "к", "t": "е", "y": "н", "u": "г", "i": "ш", "o": "щ", "p": "з",
    "a": "ф", "s": "ы", "d": "в", "f": "а", "g": "п", "h": "р", "j": "о", "k": "л", "l": "д",
    "z": "я", "x": "ч", "c": "с", "v": "м", "b": "и", "n": "т", "m": "ь",
}

# Tab / Shift+Tab aliases
SHIFT_TAB_KEYS: tuple[str, ...] = ("shift+tab", "backtab", "shift_tab")
TAB_KEYS: tuple[str, ...] = ("tab", "shift+tab", "backtab", "shift_tab")

# Predefined key combinations for ChatInput and modal event handlers
KEY_QUIT: tuple[str, ...] = ("ctrl+c", "ctrl+q", "ctrl+с", "ctrl+С", "ctrl+й", "ctrl+Й")
KEY_COPY: tuple[str, ...] = (
    "ctrl+c", "cmd+c", "ctrl+с", "ctrl+С", "cmd+с", "cmd+С", "super+c"
)
KEY_CUT: tuple[str, ...] = (
    "ctrl+x", "cmd+x", "ctrl+ч", "ctrl+Ч", "cmd+ч", "cmd+Ч", "super+x"
)
KEY_PASTE: tuple[str, ...] = (
    "ctrl+v", "cmd+v", "ctrl+м", "ctrl+М", "cmd+м", "cmd+М", "ctrl+m", "ctrl+M"
)
KEY_DETACH: tuple[str, ...] = ("ctrl+d", "cmd+d", "ctrl+в", "ctrl+В", "cmd+в", "cmd+В")
KEY_TOGGLE_ROLE: tuple[str, ...] = SHIFT_TAB_KEYS
KEY_NEWLINE: tuple[str, ...] = ("ctrl+enter", "ctrl+j", "shift+enter")
KEY_TOGGLE_DISABLED: tuple[str, ...] = ("tab", "ctrl+t", "ctrl_t", "ctrl+i", "ctrl+е", "ctrl+Е")


def get_key_aliases(key: str) -> tuple[str, ...]:
    """Generate all known layout (Cyrillic RU), modifier, and case aliases for a given key string.

    Args:
        key: Key definition string (e.g., 'ctrl+c', 'shift+tab', 'k', 'ctrl+v').

    Returns:
        A tuple of unique alias strings including the original key.
    """
    aliases: list[str] = [key]
    lower_key = key.lower()

    if lower_key in ("shift+tab", "backtab", "shift_tab"):
        for k in SHIFT_TAB_KEYS:
            if k not in aliases:
                aliases.append(k)
        return tuple(aliases)

    if lower_key in ("ctrl+enter", "ctrl+j", "shift+enter"):
        for k in KEY_NEWLINE:
            if k not in aliases:
                aliases.append(k)
        return tuple(aliases)

    # Modifier keys: ctrl+, cmd+, shift+, alt+
    for prefix in ("ctrl+", "cmd+", "shift+", "alt+"):
        if lower_key.startswith(prefix):
            char = lower_key[len(prefix):]
            if char in QWERTY_TO_RU:
                ru_char = QWERTY_TO_RU[char]
                for variant in (f"{prefix}{ru_char}", f"{prefix}{ru_char.upper()}"):
                    if variant not in aliases:
                        aliases.append(variant)
            # Extra convenience aliases for paste/detach/toggle
            if prefix == "ctrl+" and char == "v":
                for extra in ("cmd+v", "ctrl+м", "ctrl+М", "cmd+м", "cmd+М", "ctrl+m", "ctrl+M"):
                    if extra not in aliases:
                        aliases.append(extra)
            elif prefix == "ctrl+" and char == "d":
                for extra in ("cmd+d", "ctrl+в", "ctrl+В", "cmd+в", "cmd+В"):
                    if extra not in aliases:
                        aliases.append(extra)
            elif prefix == "ctrl+" and char == "t":
                for extra in ("ctrl_t", "ctrl+i", "ctrl+е", "ctrl+Е"):
                    if extra not in aliases:
                        aliases.append(extra)
            return tuple(aliases)

    # Single alphabetical characters
    if len(lower_key) == 1 and lower_key in QWERTY_TO_RU:
        ru_char = QWERTY_TO_RU[lower_key]
        for variant in (ru_char, ru_char.upper()):
            if variant not in aliases:
                aliases.append(variant)

    return tuple(aliases)


def expand_bindings(
    bindings: Sequence[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Expand a list of Textual binding tuples with cross-layout aliases.

    Original bindings keep their descriptions; generated layout aliases
    are appended with the same action and description.

    Args:
        bindings: Sequence of (key, action, description) tuples.

    Returns:
        Expanded list of binding tuples with duplicates removed.
    """
    seen_keys: set[str] = set()
    result: list[tuple[str, str, str]] = []

    for item in bindings:
        key, action, desc = item[0], item[1], item[2]
        if key not in seen_keys:
            seen_keys.add(key)
            result.append((key, action, desc))

        for alias in get_key_aliases(key):
            if alias not in seen_keys:
                seen_keys.add(alias)
                result.append((alias, action, desc))

    return result
