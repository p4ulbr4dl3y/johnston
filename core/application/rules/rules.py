import os
from typing import List, Optional

from core.domain.entities.rules import RuleDefinition
from core.infrastructure.runtime.markdown_scanner import MarkdownScannerCache


class RulesManager:
    _instance: Optional["RulesManager"] = None

    def __init__(self):
        self.rules: List[RuleDefinition] = []
        self._cache = MarkdownScannerCache(subpath="rules")

    @classmethod
    def get_instance(cls) -> "RulesManager":
        if cls._instance is None:
            cls._instance = RulesManager()
        return cls._instance

    def load_rules(self, project_dir: Optional[str] = None, include_global: bool = True) -> List[RuleDefinition]:
        p_dir = project_dir or os.getcwd()

        def _build(_dirs, files):
            rules: List[RuleDefinition] = []
            for fpath, source in files:
                rule = self._parse_rule_file(fpath, source)
                if rule:
                    rules.append(rule)
            return rules

        self.rules = self._cache.get(
            project_dir=p_dir,
            include_global=include_global,
            build=_build,
        )
        return list(self.rules)

    def invalidate_cache(self) -> None:
        """Force the next load_rules to re-scan from disk."""
        self._cache.invalidate()

    def _parse_rule_file(self, fpath: str, source: str) -> Optional[RuleDefinition]:
        try:
            from core.infrastructure.runtime.frontmatter import parse_frontmatter

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
