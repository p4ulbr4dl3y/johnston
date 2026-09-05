import logging
import re
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import tree_sitter
    import tree_sitter_go as tsgo
    import tree_sitter_javascript as tsjs
    import tree_sitter_python as tspy
    import tree_sitter_rust as tsrust
    import tree_sitter_typescript as tsts

    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    tree_sitter = None


class TreeSitterExtractor:
    """Fast, accurate AST symbol extractor powered by Tree-sitter and S-expression queries."""

    def __init__(self) -> None:
        self._languages: Dict[str, "tree_sitter.Language"] = {}
        self._queries: Dict[str, "tree_sitter.Query"] = {}
        self._local = threading.local()
        self._init_languages()

    def _get_parser(self, ext: str) -> Optional["tree_sitter.Parser"]:
        if not TREE_SITTER_AVAILABLE or ext not in self._languages:
            return None
        parsers = getattr(self._local, "parsers", None)
        if parsers is None:
            parsers = {}
            self._local.parsers = parsers
        if ext not in parsers:
            parsers[ext] = tree_sitter.Parser(self._languages[ext])
        return parsers[ext]

    def _init_languages(self) -> None:
        if not TREE_SITTER_AVAILABLE:
            return

        # Python
        try:
            py_lang = tree_sitter.Language(tspy.language())
            self._languages[".py"] = py_lang
            self._languages[".pyi"] = py_lang
            py_q = tree_sitter.Query(
                py_lang,
                """
                (class_definition
                  name: (identifier) @cls.name
                  superclasses: (argument_list)? @cls.bases) @cls

                (function_definition
                  name: (identifier) @fn.name
                  parameters: (parameters) @fn.params) @fn
                """,
            )
            self._queries[".py"] = py_q
            self._queries[".pyi"] = py_q
        except Exception as e:
            logger.debug("Tree-sitter Python init error: %s", e)

        # JavaScript
        try:
            js_lang = tree_sitter.Language(tsjs.language())
            for ext in (".js", ".jsx", ".mjs", ".cjs"):
                self._languages[ext] = js_lang
            js_query = tree_sitter.Query(
                js_lang,
                """
                (function_declaration
                  name: (identifier) @fn.name
                  parameters: (formal_parameters) @fn.params) @fn

                (class_declaration
                  name: (identifier) @cls.name) @cls

                (method_definition
                  name: (property_identifier) @method.name
                  parameters: (formal_parameters) @method.params) @method

                (variable_declarator
                  name: (identifier) @arrow.name
                  value: (arrow_function)) @arrow
                """,
            )
            for ext in (".js", ".jsx", ".mjs", ".cjs"):
                self._queries[ext] = js_query
        except Exception as e:
            logger.debug("Tree-sitter JavaScript init error: %s", e)

        # TypeScript / TSX
        try:
            ts_lang = tree_sitter.Language(tsts.language_typescript())
            tsx_lang = tree_sitter.Language(tsts.language_tsx())
            self._languages[".ts"] = ts_lang
            self._languages[".tsx"] = tsx_lang
            ts_query_str = """
                (function_declaration
                  name: (identifier) @fn.name
                  parameters: (formal_parameters) @fn.params) @fn

                (class_declaration
                  name: (type_identifier) @cls.name) @cls

                (abstract_class_declaration
                  name: (type_identifier) @cls.name) @cls

                (interface_declaration
                  name: (type_identifier) @iface.name) @iface

                (type_alias_declaration
                  name: (type_identifier) @type.name) @type

                (enum_declaration
                  name: (identifier) @enum.name) @enum

                (method_definition
                  name: (property_identifier) @method.name
                  parameters: (formal_parameters) @method.params) @method

                (variable_declarator
                  name: (identifier) @arrow.name
                  value: (arrow_function)) @arrow
            """
            self._queries[".ts"] = tree_sitter.Query(ts_lang, ts_query_str)
            self._queries[".tsx"] = tree_sitter.Query(tsx_lang, ts_query_str)
        except Exception as e:
            logger.debug("Tree-sitter TypeScript init error: %s", e)

        # Go
        try:
            go_lang = tree_sitter.Language(tsgo.language())
            self._languages[".go"] = go_lang
            self._queries[".go"] = tree_sitter.Query(
                go_lang,
                """
                (type_declaration
                  (type_spec
                    name: (type_identifier) @type.name) @type)

                (function_declaration
                  name: (identifier) @fn.name
                  parameters: (parameter_list) @fn.params) @fn

                (method_declaration
                  receiver: (parameter_list)? @method.rcvr
                  name: (field_identifier) @method.name
                  parameters: (parameter_list) @method.params) @method
                """,
            )
        except Exception as e:
            logger.debug("Tree-sitter Go init error: %s", e)

        # Rust
        try:
            rs_lang = tree_sitter.Language(tsrust.language())
            self._languages[".rs"] = rs_lang
            self._queries[".rs"] = tree_sitter.Query(
                rs_lang,
                """
                (struct_item
                  name: (type_identifier) @struct.name) @struct

                (enum_item
                  name: (type_identifier) @enum.name) @enum

                (trait_item
                  name: (type_identifier) @trait.name) @trait

                (impl_item
                  trait: (type_identifier)? @impl.trait
                  type: (type_identifier)? @impl.name) @impl

                (function_item
                  name: (identifier) @fn.name
                  parameters: (parameters) @fn.params) @fn

                (function_signature_item
                  name: (identifier) @fn.name
                  parameters: (parameters) @fn.params) @fn

                (mod_item
                  name: (identifier) @mod.name) @mod
                """,
            )
        except Exception as e:
            logger.debug("Tree-sitter Rust init error: %s", e)

    def is_available(self, ext: str) -> bool:
        return ext in self._languages and ext in self._queries

    def extract_symbols(
        self,
        code: str,
        ext: str,
        query: Optional[str] = None,
    ) -> List[Tuple[str, int, str]]:
        """Extract symbols using Tree-sitter.

        Returns list of tuples: (display_line, 1_based_line_number, raw_symbol_name).
        """
        if not self.is_available(ext):
            return []

        parser = self._get_parser(ext)
        if not parser:
            return []
        q_obj = self._queries[ext]
        code_bytes = code.encode("utf-8")
        tree = parser.parse(code_bytes)

        cursor = tree_sitter.QueryCursor(q_obj)
        matches = cursor.matches(tree.root_node)

        raw_results: List[Tuple[str, int, str, int]] = []
        q_lower = query.lower().strip() if query and query.strip() and query.strip() != "*" else None

        for _, captures in matches:
            symbol_tuple = self._format_capture(captures, ext)
            if not symbol_tuple:
                continue
            display, lineno, name, start_byte = symbol_tuple
            if q_lower is not None and q_lower not in name.lower():
                continue
            raw_results.append((display, lineno, name, start_byte))

        raw_results.sort(key=lambda x: x[3])
        return [(r[0], r[1], r[2]) for r in raw_results]

    def _format_python_params(self, params_node: Optional["tree_sitter.Node"]) -> str:
        if not params_node:
            return "()"
        names = []
        for c in params_node.children:
            if c.type == "identifier":
                names.append(c.text.decode("utf-8", errors="replace"))
            elif c.type in ("typed_parameter", "typed_default_parameter"):
                if c.children:
                    first = c.children[0]
                    if first.type in ("identifier", "list_splat_pattern", "dictionary_splat_pattern"):
                        names.append(first.text.decode("utf-8", errors="replace"))
            elif c.type == "default_parameter":
                name_node = c.child_by_field_name("name")
                if name_node:
                    names.append(name_node.text.decode("utf-8", errors="replace"))
                elif c.children and c.children[0].type == "identifier":
                    names.append(c.children[0].text.decode("utf-8", errors="replace"))
            elif c.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                names.append(c.text.decode("utf-8", errors="replace"))
            elif c.type in ("positional_separator", "keyword_separator", "/", "*"):
                names.append(c.text.decode("utf-8", errors="replace") if c.text else c.type)
        return "(" + ", ".join(names) + ")"

    def _format_capture(
        self,
        captures: Dict[str, List["tree_sitter.Node"]],
        ext: str,
    ) -> Optional[Tuple[str, int, str, int]]:
        for key in (
            "cls", "fn", "method", "arrow", "iface", "type", "enum",
            "struct", "trait", "impl", "mod",
        ):
            if key in captures:
                node = captures[key][0]
                if node.has_error:
                    return None

                name_key = f"{key}.name"
                name = (
                    captures[name_key][0].text.decode("utf-8", errors="replace")
                    if name_key in captures
                    else ""
                )
                if key == "impl":
                    trait_node = node.child_by_field_name("trait")
                    type_node = node.child_by_field_name("type")
                    trait_name = (
                        trait_node.text.decode("utf-8", errors="replace")
                        if trait_node
                        else (captures.get("impl.trait", [None])[0].text.decode("utf-8", errors="replace") if "impl.trait" in captures else "")
                    )
                    type_name = (
                        type_node.text.decode("utf-8", errors="replace")
                        if type_node
                        else name
                    )
                    if trait_name and type_name:
                        name = f"{trait_name} for {type_name}"
                    elif trait_name:
                        name = trait_name
                    elif type_name:
                        name = type_name
                    elif not name:
                        impl_text = node.text.decode("utf-8", errors="replace").split("{")[0].strip()
                        name = re.sub(r"^impl\b\s*", "", impl_text).strip()
                if not name:
                    name = node.type

                lineno = node.start_point[0] + 1
                start_byte = node.start_byte

                parent = node.parent
                depth = 0
                while parent:
                    if parent.type in ("class_definition", "class_declaration", "abstract_class_declaration", "impl_item"):
                        depth += 1
                    parent = parent.parent
                indent = "  " * (1 + depth)

                if ext in (".py", ".pyi"):
                    if key == "cls":
                        bases = ""
                        if "cls.bases" in captures:
                            bases = captures["cls.bases"][0].text.decode("utf-8", errors="replace")
                        return f"{indent}{lineno}: class {name}{bases}:", lineno, name, start_byte
                    if key == "fn":
                        params_node = captures.get("fn.params", [None])[0]
                        params = self._format_python_params(params_node)
                        is_async = any(c.type == "async" for c in node.children)
                        prefix = "async def" if is_async else "def"
                        return f"{indent}{lineno}: {prefix} {name}{params}", lineno, name, start_byte

                elif ext in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"):
                    if key == "cls":
                        return f"{indent}{lineno}: class {name}", lineno, name, start_byte
                    if key == "iface":
                        return f"{indent}{lineno}: interface {name}", lineno, name, start_byte
                    if key == "type":
                        return f"{indent}{lineno}: type {name} = ...", lineno, name, start_byte
                    if key == "enum":
                        return f"{indent}{lineno}: enum {name}", lineno, name, start_byte
                    if key == "fn":
                        params = "()"
                        if "fn.params" in captures:
                            params = captures["fn.params"][0].text.decode("utf-8", errors="replace")
                        is_async = any(c.type == "async" for c in node.children)
                        prefix = "async function" if is_async else "function"
                        return f"{indent}{lineno}: {prefix} {name}{params}", lineno, name, start_byte
                    if key == "method":
                        params = "()"
                        if "method.params" in captures:
                            params = captures["method.params"][0].text.decode("utf-8", errors="replace")
                        return f"{indent}{lineno}: {name}{params}", lineno, name, start_byte
                    if key == "arrow":
                        return f"{indent}{lineno}: const {name} = (...) =>", lineno, name, start_byte

                elif ext == ".go":
                    if key == "type":
                        type_node = captures.get("type.spec", [node])[0]
                        type_text = type_node.text.decode("utf-8", errors="replace").split("{")[0].strip()
                        return f"{indent}{lineno}: type {type_text}", lineno, name, start_byte
                    if key == "fn":
                        params = "()"
                        if "fn.params" in captures:
                            params = captures["fn.params"][0].text.decode("utf-8", errors="replace")
                        return f"{indent}{lineno}: func {name}{params}", lineno, name, start_byte
                    if key == "method":
                        rcvr = ""
                        if "method.rcvr" in captures:
                            rcvr = captures["method.rcvr"][0].text.decode("utf-8", errors="replace") + " "
                        params = "()"
                        if "method.params" in captures:
                            params = captures["method.params"][0].text.decode("utf-8", errors="replace")
                        return f"{indent}{lineno}: func {rcvr}{name}{params}", lineno, name, start_byte

                elif ext == ".rs":
                    if key == "struct":
                        return f"{indent}{lineno}: struct {name}", lineno, name, start_byte
                    if key == "enum":
                        return f"{indent}{lineno}: enum {name}", lineno, name, start_byte
                    if key == "trait":
                        return f"{indent}{lineno}: trait {name}", lineno, name, start_byte
                    if key == "impl":
                        return f"{indent}{lineno}: impl {name}", lineno, name, start_byte
                    if key == "fn":
                        params = "()"
                        if "fn.params" in captures:
                            params = captures["fn.params"][0].text.decode("utf-8", errors="replace")
                        return f"{indent}{lineno}: fn {name}{params}", lineno, name, start_byte
                    if key == "mod":
                        return f"{indent}{lineno}: mod {name}", lineno, name, start_byte

                return f"{indent}{lineno}: {name}", lineno, name, start_byte

        return None


GLOBAL_TREE_SITTER: Optional[TreeSitterExtractor] = (
    TreeSitterExtractor() if TREE_SITTER_AVAILABLE else None
)
