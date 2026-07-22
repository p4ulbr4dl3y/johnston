import os

CONFIG_DIR = os.path.expanduser("~/.johnston")
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROVIDERS_DIR = os.path.join(PROJECT_DIR, "providers")
PROJECTS_DIR = os.path.join(CONFIG_DIR, "projects")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Theme Palette Constants (Monochrome Slate)
THEME_BG = "#09090b"
THEME_CARD = "#18181b"
THEME_BORDER = "#27272a"
THEME_PRIMARY = "#ffffff"
THEME_SECONDARY = "#f4f4f5"
THEME_MUTED = "#71717a"
THEME_SUBTLE = "#e4e4e7"
