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
    "explorer": SubagentDefinition(
        name="explorer",
        subagent_type="explorer",
        description="Fast code exploration subagent",
        system_prompt=(
            "## Subagent Mode: EXPLORER\n\n"
            "You are a read-only exploration subagent operating inside Johnston CLI.\n\n"
            "## Primary Goal\n"
            "Search codebase, analyze files, and report findings concisely without altering system state.\n\n"
            "## Core Rules\n"
            "1. Read-Only Restriction: Never create, edit, or delete files. Do not run state-changing shell commands (no rm, mv, touch, or > / >> redirects).\n"
            "2. Broad-to-Narrow Search: Start broad with grep/search, then inspect specific file contents.\n"
            "3. Parallel Tool Calls: Issue parallel tool invocations when reading or searching multiple files.\n"
            "4. Text Report Only: Communicate findings directly in text response. Never create report files."
        ),
        source="builtin",
    ),
    "worker": SubagentDefinition(
        name="worker",
        subagent_type="worker",
        description="General multi-step execution subagent",
        system_prompt=(
            "## Subagent Mode: WORKER\n\n"
            "You are a task execution subagent operating inside Johnston CLI.\n\n"
            "## Primary Goal\n"
            "Perform multi-step engineering tasks safely and return concise, actionable results.\n\n"
            "## Core Rules\n"
            "1. Complete Execution: Finish the task fully. Do not gold-plate, but do not leave work half-done.\n"
            "2. File Preservation: Prefer editing existing files over creating new ones. Never create .md documentation files unless requested.\n"
            "3. Concise Reporting: Return a succinct summary of actions taken and key findings for the main session."
        ),
        source="builtin",
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

            if fname.endswith(".md") or fname.endswith(".markdown"):
                self._load_markdown(fpath, source)

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
        return DEFAULT_DEFINITIONS["worker"]

    def list_definitions(self) -> Dict[str, SubagentDefinition]:
        return self.definitions

    def get_system_prompt_snippet(self, project_dir: Optional[str] = None) -> str:
        self.reload(project_dir=project_dir)
        if not self.definitions:
            return ""

        builtins = []
        globals_list = []
        project_list = []

        for defn in self.definitions.values():
            tools_str = f" (Tools: {', '.join(defn.tools)})" if defn.tools else ""
            desc = f": {defn.description}" if defn.description else ""
            line = f"- `{defn.name}`{desc}{tools_str}"
            if defn.source == "builtin":
                builtins.append(line)
            elif defn.source == "global":
                globals_list.append(line)
            elif defn.source == "project":
                project_list.append(line)

        lines = ["## Subagents (use as `subagent_type` in `invoke_subagent`)"]
        if builtins:
            lines.append("\n### Builtin")
            lines.extend(builtins)
        if globals_list:
            lines.append("\n### Global (`~/.johnston/subagents/definitions/<name>.md`)")
            lines.extend(globals_list)
        if project_list:
            lines.append("\n### Project (`.johnston/subagents/<name>.md`)")
            lines.extend(project_list)

        return "\n".join(lines)

