import os
import time
from typing import List, Optional, Tuple

from core.config import CONFIG_DIR
from core.frontmatter import iter_md_files, parse_csv_list, parse_frontmatter


class RuleDefinition:
    def __init__(
        self,
        name: str,
        content: str,
        roles: Optional[List[str]] = None,
        source: str = "global",
    ):
        self.name = name
        self.content = content
        self.roles = [r.lower().strip() for r in (roles or [])]
        self.source = source

    def is_active_for_roles(self, role: str) -> bool:
        if not self.roles:
            return True
        return role.lower().strip() in self.roles


class RulesManager:
    _instance: Optional["RulesManager"] = None

    _CACHE_TTL = 2.0  # seconds

    def __init__(self):
        self.rules: List[RuleDefinition] = []
        self._rules_cache_signature: Optional[tuple] = None
        self._rules_cache_ts: float = 0.0

    @classmethod
    def get_instance(cls) -> "RulesManager":
        if cls._instance is None:
            cls._instance = RulesManager()
        return cls._instance

    def load_rules(self, project_dir: Optional[str] = None, include_global: bool = True) -> List[RuleDefinition]:
        p_dir = project_dir or os.getcwd()
        dirs = []
        if include_global:
            dirs.append((os.path.join(CONFIG_DIR, "rules"), "global"))
        dirs.append((os.path.join(p_dir, ".johnston", "rules"), "project"))

        now = time.time()
        signature = self._rules_signature(dirs)
        if (
            signature is not None
            and signature == self._rules_cache_signature
            and (now - self._rules_cache_ts) < self._CACHE_TTL
        ):
            return list(self.rules)

        rules: List[RuleDefinition] = []
        for fpath, source in iter_md_files(dirs):
            rule = self._parse_rule_file(fpath, source)
            if rule:
                rules.append(rule)

        self.rules = rules
        self._rules_cache_signature = signature
        self._rules_cache_ts = now
        return rules

    @staticmethod
    def _rules_signature(dirs: List[Tuple[str, str]]) -> Optional[Tuple]:
        """Cheap (relpath, mtime_ns, size) signature of every rule file to detect
        external changes without re-reading contents. None when dirs are absent."""
        entries = []
        for dpath, _source in dirs:
            if not os.path.isdir(dpath):
                continue
            try:
                for fname in sorted(os.listdir(dpath)):
                    if not (fname.endswith(".md") or fname.endswith(".markdown")):
                        continue
                    fpath = os.path.join(dpath, fname)
                    if not os.path.isfile(fpath):
                        continue
                    st = os.stat(fpath)
                    entries.append((fpath, st.st_mtime_ns, st.st_size))
            except OSError:
                continue
        return tuple(entries)

    def invalidate_cache(self) -> None:
        """Force the next load_rules/get_formatted_rules to re-scan from disk."""
        self._rules_cache_signature = None
        self._rules_cache_ts = 0.0

    def _parse_rule_file(self, fpath: str, source: str) -> Optional[RuleDefinition]:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read().strip()
            if not raw:
                return None

            base_name = os.path.splitext(os.path.basename(fpath))[0]
            meta, content = parse_frontmatter(raw)
            content = content.strip()

            name = meta.get("name") or base_name
            modes_raw = meta.get("role") or meta.get("roles") or meta.get("mode") or meta.get("modes") or ""
            roles = parse_csv_list(modes_raw)

            return RuleDefinition(name=name, content=content, roles=roles, source=source)
        except Exception:
            return None

    def get_formatted_rules(
        self, role: str = "worker", project_dir: Optional[str] = None
    ) -> str:
        rules = self.load_rules(project_dir=project_dir)
        matching = []
        for r in rules:
            if r.is_active_for_roles(role):
                matching.append(f"### Rule: {r.name}\n{r.content}")

        return "\n\n".join(matching)
