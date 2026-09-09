import os
import threading
from typing import List, Optional

from johnston.core.domain.entities.rules import RuleDefinition
from johnston.core.infrastructure.runtime.markdown_scanner import MarkdownScannerCache

_rules_singleton_lock = threading.Lock()


class RulesManager:
    _instance: Optional["RulesManager"] = None

    def __init__(self):
        self._rules: List[RuleDefinition] = []
        self._cache = MarkdownScannerCache(subpath="rules")
        self._lock = threading.Lock()

    @property
    def rules(self) -> List[RuleDefinition]:
        with self._lock:
            return list(self._rules)

    @rules.setter
    def rules(self, val: List[RuleDefinition]) -> None:
        with self._lock:
            self._rules = list(val)

    @classmethod
    def get_instance(cls) -> "RulesManager":
        if cls._instance is None:
            with _rules_singleton_lock:
                if cls._instance is None:
                    cls._instance = RulesManager()
        return cls._instance

    def load_rules(self, project_dir: Optional[str] = None, include_global: bool = True) -> List[RuleDefinition]:
        with self._lock:
            p_dir = project_dir or os.getcwd()

            def _build(_dirs, files):
                rules: List[RuleDefinition] = []
                for fpath, source in files:
                    rule = self._parse_rule_file(fpath, source)
                    if rule:
                        rules.append(rule)
                return rules

            self._rules = self._cache.get(
                project_dir=p_dir,
                include_global=include_global,
                build=_build,
            )
            return list(self._rules)

    def invalidate_cache(self) -> None:
        """Force the next load_rules to re-scan from disk."""
        with self._lock:
            self._cache.invalidate()

    def _parse_rule_file(self, fpath: str, source: str) -> Optional[RuleDefinition]:
        try:
            from johnston.core.infrastructure.runtime.frontmatter import parse_frontmatter

            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read().strip()
            if not raw:
                return None

            name = os.path.splitext(os.path.basename(fpath))[0]
            _, content = parse_frontmatter(raw)
            return RuleDefinition(name=name, content=content.strip(), source=source)
        except Exception:
            return None

    def get_active_rules(
        self, project_dir: Optional[str] = None, include_global: bool = True
    ) -> List[RuleDefinition]:
        """Return the active ``RuleDefinition`` objects.

        Data-only: leaves Markdown assembly (``### Rule: ...``) to the prompt
        builder so this application module does not own rendering output.
        """
        return self.load_rules(project_dir=project_dir, include_global=include_global)
