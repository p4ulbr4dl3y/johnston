import json
import os
from typing import Dict, List, Optional

from core.config import SUBAGENT_DEFS_DIR


class SubagentDefinition:
    def __init__(
        self,
        name: str,
        description: str,
        system_prompt: str,
        tools: Optional[List[str]] = None,
        model: str = "",
        subagent_type: str = "",
        source: str = "builtin"
    ):
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.model = model
        self.subagent_type = subagent_type or name
        self.source = source



DEFAULT_DEFINITIONS: Dict[str, SubagentDefinition] = {
    "explore": SubagentDefinition(
        name="explore",
        description="Fast code exploration subagent",
        system_prompt="[SUBAGENT EXPLORE MODE]\nYou are a read-only exploration subagent. Search codebase, read files, run search commands, and summarize findings concisely.",
        source="builtin"
    ),
    "general": SubagentDefinition(
        name="general",
        description="General multi-step execution subagent",
        system_prompt="[SUBAGENT GENERAL MODE]\nYou are a subagent executing tasks. Perform the task and return concise results.",
        source="builtin"
    ),
}


class SubagentRegistry:
    _instance: Optional["SubagentRegistry"] = None

    def __init__(self):
        self.definitions: Dict[str, SubagentDefinition] = {}
        self.reload()

    @classmethod
    def get_instance(cls) -> "SubagentRegistry":
        if cls._instance is None:
            cls._instance = SubagentRegistry()
        return cls._instance

    def reload(self, project_dir: Optional[str] = None) -> None:
        self.definitions = {k: v for k, v in DEFAULT_DEFINITIONS.items()}
        # 1. Global definitions (~/.johnston/subagents/definitions/)
        self._load_from_dir(SUBAGENT_DEFS_DIR, source="global")
        # 2. Project definitions (<project_dir>/.johnston/subagents/)
        if project_dir:
            proj_defs = os.path.join(project_dir, ".johnston", "subagents")
            self._load_from_dir(proj_defs, source="project")

    def _load_from_dir(self, directory: str, source: str) -> None:
        if not os.path.exists(directory):
            return

        for fname in os.listdir(directory):
            fpath = os.path.join(directory, fname)
            if not os.path.isfile(fpath):
                continue

            if fname.endswith(".json"):
                self._load_json(fpath, source)
            elif fname.endswith(".md") or fname.endswith(".markdown"):
                self._load_markdown(fpath, source)

    def _load_json(self, fpath: str, source: str) -> None:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("name") or data.get("subagent_type") or os.path.splitext(os.path.basename(fpath))[0]
            desc = data.get("description", "Custom subagent")
            prompt = data.get("system_prompt") or data.get("prompt", "")
            tools = data.get("tools", [])
            model = data.get("model", "")
            self.definitions[name.lower()] = SubagentDefinition(
                name=name, description=desc, system_prompt=prompt, tools=tools, model=model, source=source
            )
        except Exception:
            pass

    def _load_markdown(self, fpath: str, source: str) -> None:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()

            meta = {}
            prompt = content
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    yaml_text = parts[1].strip()
                    prompt = parts[2].strip()
                    for line in yaml_text.splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            meta[k.strip().lower()] = v.strip().strip("\"'")

            name = meta.get("name") or meta.get("subagent_type") or os.path.splitext(os.path.basename(fpath))[0]
            desc = meta.get("description", "Custom subagent")
            model = meta.get("model", "")
            tools_str = meta.get("tools", "")
            tools = [t.strip() for t in tools_str.split(",")] if tools_str else []

            self.definitions[name.lower()] = SubagentDefinition(
                name=name, description=desc, system_prompt=prompt, tools=tools, model=model, source=source
            )
        except Exception:
            pass

    def get_definition(self, subagent_type: str) -> SubagentDefinition:
        key = subagent_type.lower().strip()
        if key in self.definitions:
            return self.definitions[key]
        return DEFAULT_DEFINITIONS.get("general", SubagentDefinition("general", "General subagent", ""))

    def list_definitions(self) -> Dict[str, SubagentDefinition]:
        return self.definitions
