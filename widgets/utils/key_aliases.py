"""Keybinding aliases and layout normalization for terminal and cross-layout compatibility.

Provides multi-layout aliases (Cyrillic RU/UA/BY/SR, Greek, Hebrew, Arabic, Georgian, Armenian)
for Ctrl/Cmd combos, single-character navigation keys, and Textual screen bindings
to ensure hotkeys work regardless of active keyboard layout.
"""

from typing import Sequence

# Layout mappings (QWERTY latin -> localized characters)
QWERTY_TO_RU: dict[str, str] = {
    "q": "й", "w": "ц", "e": "у", "r": "к", "t": "е", "y": "н", "u": "г", "i": "ш", "o": "щ", "p": "з",
    "a": "ф", "s": "ы", "d": "в", "f": "а", "g": "п", "h": "р", "j": "о", "k": "л", "l": "д",
    "z": "я", "x": "ч", "c": "с", "v": "м", "b": "и", "n": "т", "m": "ь",
    "[": "х", "]": "ъ", ";": "ж", "'": "э", ",": "б", ".": "ю",
}

QWERTY_TO_UA_BY: dict[str, str] = {
    "s": "і", "g": "ґ", "u": "ў", "]": "ї", "'": "є",
}

QWERTY_TO_SR: dict[str, str] = {
    "q": "љ", "w": "њ", "e": "е", "r": "р", "t": "т", "y": "з", "u": "у", "i": "и", "o": "о", "p": "п",
    "a": "а", "s": "с", "d": "д", "f": "ф", "g": "г", "h": "х", "j": "ј", "k": "к", "l": "л",
    "z": "ж", "x": "џ", "c": "ц", "v": "в", "b": "б", "n": "н", "m": "м",
}

QWERTY_TO_EL: dict[str, str] = {
    "q": ";", "w": "ς", "e": "ε", "r": "ρ", "t": "τ", "y": "υ", "u": "θ", "i": "ι", "o": "ο", "p": "π",
    "a": "α", "s": "σ", "d": "δ", "f": "φ", "g": "γ", "h": "η", "j": "ξ", "k": "κ", "l": "λ",
    "z": "ζ", "x": "χ", "c": "ψ", "v": "ω", "b": "β", "n": "ν", "m": "μ",
}

QWERTY_TO_HE: dict[str, str] = {
    "q": "/", "w": "'", "e": "ק", "r": "ר", "t": "א", "y": "ט", "u": "ו", "i": "ן", "o": "ם", "p": "פ",
    "a": "ש", "s": "ד", "d": "ג", "f": "כ", "g": "ע", "h": "י", "j": "ח", "k": "ל", "l": "ך",
    "z": "ז", "x": "ס", "c": "ב", "v": "ה", "b": "נ", "n": "מ", "m": "צ",
    ",": "ת", ".": "ץ",
}

QWERTY_TO_AR: dict[str, str] = {
    "q": "ض", "w": "ص", "e": "ث", "r": "ق", "t": "ف", "y": "غ", "u": "ع", "i": "ه", "o": "خ", "p": "ح",
    "a": "ش", "s": "س", "d": "ي", "f": "ب", "g": "ل", "h": "ا", "j": "ت", "k": "ن", "l": "م",
    "z": "ئ", "x": "ء", "c": "ؤ", "v": "ر", "b": "لا", "n": "ى", "m": "ة",
    "[": "ج", "]": "د", ";": "ك", "'": "ط", ",": "و", ".": "ز",
}

QWERTY_TO_KA: dict[str, str] = {
    "q": "ქ", "w": "წ", "e": "ე", "r": "რ", "t": "ტ", "y": "ყ", "u": "უ", "i": "ი", "o": "ო", "p": "პ",
    "a": "ა", "s": "ს", "d": "დ", "f": "ფ", "g": "გ", "h": "ჰ", "j": "ჯ", "k": "კ", "l": "ლ",
    "z": "ზ", "x": "ხ", "c": "ც", "v": "ვ", "b": "ბ", "n": "ნ", "m": "მ",
}

QWERTY_TO_HY: dict[str, str] = {
    "q": "ք", "w": "ո", "e": "ե", "r": "ր", "t": "տ", "y": "ը", "u": "ւ", "i": "ի", "o": "օ", "p": "պ",
    "a": "ա", "s": "ս", "d": "դ", "f": "ֆ", "g": "գ", "h": "հ", "j": "յ", "k": "կ", "l": "լ",
    "z": "զ", "x": "ղ", "c": "ց", "v": "վ", "b": "բ", "n": "ն", "m": "մ",
}

SUPPORTED_LAYOUT_MAPS: tuple[dict[str, str], ...] = (
    QWERTY_TO_RU,
    QWERTY_TO_UA_BY,
    QWERTY_TO_SR,
    QWERTY_TO_EL,
    QWERTY_TO_HE,
    QWERTY_TO_AR,
    QWERTY_TO_KA,
    QWERTY_TO_HY,
)

# Reverse mapping from any localized character to base Latin character
CHAR_TO_LATIN: dict[str, str] = {}
# Mapping from Latin character to list of all layout character aliases
LATIN_TO_LAYOUT_CHARS: dict[str, tuple[str, ...]] = {}

for layout_map in SUPPORTED_LAYOUT_MAPS:
    for latin, char in layout_map.items():
        if char.lower() not in CHAR_TO_LATIN:
            CHAR_TO_LATIN[char.lower()] = latin.lower()
        if char.upper() != char.lower() and char.upper() not in CHAR_TO_LATIN:
            CHAR_TO_LATIN[char.upper()] = latin.lower()
        existing = LATIN_TO_LAYOUT_CHARS.setdefault(latin.lower(), ())
        if char not in existing:
            LATIN_TO_LAYOUT_CHARS[latin.lower()] = existing + (char,)

# Tab / Shift+Tab aliases
SHIFT_TAB_KEYS: tuple[str, ...] = ("shift+tab", "backtab", "shift_tab")
TAB_KEYS: tuple[str, ...] = ("tab", "shift+tab", "backtab", "shift_tab")


def normalize_key_to_latin(key: str | None) -> str:
    """Normalize a multi-layout key (e.g. Cyrillic/Hebrew/Greek/Arabic) or combo back to QWERTY latin.

    Examples:
        'ctrl+с' -> 'ctrl+c'
        'ctrl+ש' -> 'ctrl+a'
        'л' -> 'k'
        'escape' -> 'escape'
    """
    if not key:
        return ""
    lower_key = key.lower()

    for prefix in ("ctrl+", "cmd+", "shift+", "alt+"):
        if lower_key.startswith(prefix):
            raw_char = lower_key[len(prefix):]
            latin_char = CHAR_TO_LATIN.get(raw_char, raw_char)
            return f"{prefix}{latin_char}"

    return CHAR_TO_LATIN.get(lower_key, lower_key)


def get_key_aliases(key: str) -> tuple[str, ...]:
    """Generate all known layout, modifier, and case aliases for a given key string.

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
            raw_char = lower_key[len(prefix):]
            latin_char = CHAR_TO_LATIN.get(raw_char, raw_char)

            target_chars = LATIN_TO_LAYOUT_CHARS.get(latin_char, ())
            for c in (latin_char,) + target_chars:
                for variant in (f"{prefix}{c}", f"{prefix}{c.upper()}" if c.upper() != c else f"{prefix}{c}"):
                    if variant not in aliases:
                        aliases.append(variant)

            # Special convenience modifier aliases
            if latin_char == "v":
                for extra in ("cmd+v", "ctrl+m", "ctrl+M", "cmd+м", "cmd+М"):
                    if extra not in aliases:
                        aliases.append(extra)
            elif latin_char == "d":
                for extra in ("cmd+d", "cmd+в", "cmd+В"):
                    if extra not in aliases:
                        aliases.append(extra)
            elif latin_char == "x":
                for extra in ("cmd+x", "cmd+ч", "cmd+Ч", "super+x"):
                    if extra not in aliases:
                        aliases.append(extra)
            elif latin_char == "t":
                for extra in ("ctrl_t", "ctrl+i", "ctrl+е", "ctrl+Е"):
                    if extra not in aliases:
                        aliases.append(extra)
            return tuple(aliases)

    # Single localized or latin characters
    if len(lower_key) == 1:
        latin_char = CHAR_TO_LATIN.get(lower_key, lower_key)
        target_chars = LATIN_TO_LAYOUT_CHARS.get(latin_char, ())
        for c in (latin_char,) + target_chars:
            for variant in (c, c.upper()):
                if variant not in aliases:
                    aliases.append(variant)

    return tuple(aliases)


# Predefined key combinations for ChatInput and modal event handlers
KEY_QUIT: tuple[str, ...] = tuple(dict.fromkeys(get_key_aliases("ctrl+c") + get_key_aliases("ctrl+q")))
KEY_CUT: tuple[str, ...] = tuple(dict.fromkeys(get_key_aliases("ctrl+x") + get_key_aliases("cmd+x") + ("super+x",)))
KEY_PASTE: tuple[str, ...] = tuple(dict.fromkeys(
    get_key_aliases("ctrl+v") + get_key_aliases("cmd+v") + ("ctrl+m", "ctrl+M")
))
KEY_DETACH: tuple[str, ...] = tuple(dict.fromkeys(get_key_aliases("ctrl+d") + get_key_aliases("cmd+d")))
KEY_TOGGLE_ROLE: tuple[str, ...] = ("tab",)
KEY_TOGGLE_MODE: tuple[str, ...] = SHIFT_TAB_KEYS
KEY_NEWLINE: tuple[str, ...] = ("ctrl+enter", "ctrl+j", "shift+enter")
KEY_TOGGLE_DISABLED: tuple[str, ...] = tuple(dict.fromkeys(
    ("tab", "ctrl_t", "ctrl+i") + get_key_aliases("ctrl+t")
))
KEY_SCROLL_UP: tuple[str, ...] = ("pageup", "page_up")
KEY_SCROLL_DOWN: tuple[str, ...] = ("pagedown", "page_down")
KEY_SCROLL_TOP: tuple[str, ...] = ("shift+pageup", "shift+page_up", "shift+home")
KEY_SCROLL_BOTTOM: tuple[str, ...] = ("shift+pagedown", "shift+page_down", "shift+end")


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
