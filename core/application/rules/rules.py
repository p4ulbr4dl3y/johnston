import os
from typing import List, Optional

from core.infrastructure.runtime.frontmatter import parse_csv_list, parse_frontmatter
from core.infrastructure.runtime.markdown_scanner import MarkdownScannerCache


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
        """Force the next load_rules/get_formatted_rules to re-scan from disk."""
        self._cache.invalidate()

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

    def get_active_rules(
        self, role: str = "worker", project_dir: Optional[str] = None
    ) -> List[RuleDefinition]:
        """Return the ``RuleDefinition`` objects active for ``role``.

        Data-only: leaves Markdown assembly (``### Rule: ...``) to the prompt
        builder so this application module does not own rendering output.
        """
        rules = self.load_rules(project_dir=project_dir)
        return [r for r in rules if r.is_active_for_roles(role)]

    def get_formatted_rules(
        self, role: str = "worker", project_dir: Optional[str] = None
    ) -> str:
        rules = self.get_active_rules(role=role, project_dir=project_dir)
        matching = []
        for r in rules:
            matching.append(f"### Rule: {r.name}\n{r.content}")

        return "\n\n".join(matching)
