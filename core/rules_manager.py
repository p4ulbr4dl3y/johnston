import fnmatch
import os
from typing import List, Optional

from core.config import CONFIG_DIR


class RuleDefinition:
    def __init__(
        self,
        name: str,
        content: str,
        modes: Optional[List[str]] = None,
        globs: Optional[List[str]] = None,
        source: str = "global"
    ):
        self.name = name
        self.content = content
        self.modes = [m.lower().strip() for m in (modes or [])]
        self.globs = [g.strip() for g in (globs or [])]
        self.source = source

    def is_active_for_mode(self, mode: str) -> bool:
        if not self.modes:
            return True
        return mode.lower().strip() in self.modes

    def is_active_for_files(self, changed_files: List[str]) -> bool:
        if not self.globs:
            return True
        if not changed_files:
            return True
        for filepath in changed_files:
            fname = os.path.basename(filepath)
            for glob_pat in self.globs:
                if fnmatch.fnmatch(fname, glob_pat) or fnmatch.fnmatch(filepath, glob_pat):
                    return True
        return False


class RulesManager:
    _instance: Optional["RulesManager"] = None

    def __init__(self):
        self.rules: List[RuleDefinition] = []

    @classmethod
    def get_instance(cls) -> "RulesManager":
        if cls._instance is None:
            cls._instance = RulesManager()
        return cls._instance

    def load_rules(self, project_dir: Optional[str] = None, include_global: bool = True) -> List[RuleDefinition]:
        rules: List[RuleDefinition] = []
        dirs = []
        if include_global:
            dirs.append((os.path.join(CONFIG_DIR, "rules"), "global"))
        p_dir = project_dir or os.getcwd()
        dirs.append((os.path.join(p_dir, ".johnston", "rules"), "project"))

        scanned_paths = set()
        for dpath, source in dirs:
            if not os.path.isdir(dpath):
                continue
            rpath = os.path.realpath(dpath)
            if rpath in scanned_paths:
                continue
            scanned_paths.add(rpath)
            for fname in sorted(os.listdir(dpath)):
                fpath = os.path.join(dpath, fname)
                if os.path.isfile(fpath) and (fname.endswith(".md") or fname.endswith(".markdown")):
                    rule = self._parse_rule_file(fpath, source)
                    if rule:
                        rules.append(rule)

        self.rules = rules
        return rules

    def _parse_rule_file(self, fpath: str, source: str) -> Optional[RuleDefinition]:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read().strip()
            if not raw:
                return None

            base_name = os.path.splitext(os.path.basename(fpath))[0]
            meta = {}
            content = raw

            if raw.startswith("---"):
                parts = raw.split("---", 2)
                if len(parts) >= 3:
                    yaml_str = parts[1].strip()
                    content = parts[2].strip()
                    for line in yaml_str.splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            meta[k.strip().lower()] = v.strip().strip("\"'")

            name = meta.get("name") or base_name
            modes_raw = meta.get("mode") or meta.get("modes") or ""
            globs_raw = meta.get("globs") or meta.get("glob") or ""

            modes = []
            if modes_raw:
                cleaned = modes_raw.strip("[]")
                modes = [m.strip() for m in cleaned.split(",") if m.strip()]

            globs = []
            if globs_raw:
                cleaned_g = globs_raw.strip("[]")
                globs = [g.strip() for g in cleaned_g.split(",") if g.strip()]

            return RuleDefinition(
                name=name,
                content=content,
                modes=modes,
                globs=globs,
                source=source
            )
        except Exception:
            return None

    def get_formatted_rules(self, mode: str = "act", changed_files: Optional[List[str]] = None, project_dir: Optional[str] = None) -> str:
        rules = self.load_rules(project_dir=project_dir)
        matching = []
        for r in rules:
            if r.is_active_for_mode(mode) and r.is_active_for_files(changed_files or []):
                matching.append(f"### Rule: {r.name}\n{r.content}")

        return "\n\n".join(matching)
