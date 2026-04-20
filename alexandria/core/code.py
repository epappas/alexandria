"""Code structure extraction — AST and declaration parsing.

Parses source code into structured representations (functions, classes,
imports, resources) without needing an LLM. Feeds into beliefs and
enriches wiki pages with queryable facts.

Supported languages:
- Python: stdlib ``ast`` (full AST)
- TypeScript/JavaScript: declaration pattern extraction
- Rust: declaration pattern extraction
- Go: declaration pattern extraction
- YAML: ``pyyaml`` structure parsing
- Ansible: YAML with task/role/playbook awareness
- Terraform (HCL): ``python-hcl2`` if available, else pattern extraction
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParamInfo:
    """A function parameter."""

    name: str
    annotation: str = ""


@dataclass
class FunctionInfo:
    """Extracted function or method."""

    name: str
    params: list[ParamInfo] = field(default_factory=list)
    return_type: str = ""
    docstring: str = ""
    decorators: list[str] = field(default_factory=list)
    is_method: bool = False
    line: int = 0


@dataclass
class ClassInfo:
    """Extracted class/struct/interface/type definition."""

    name: str
    bases: list[str] = field(default_factory=list)
    docstring: str = ""
    methods: list[FunctionInfo] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    line: int = 0


@dataclass
class ResourceInfo:
    """Extracted infrastructure resource (Terraform, Ansible, YAML)."""

    kind: str  # e.g. "aws_instance", "task", "service"
    name: str
    attributes: dict[str, str] = field(default_factory=dict)
    line: int = 0


@dataclass
class CodeStructure:
    """Complete structural representation of a source file."""

    language: str
    module_docstring: str = ""
    imports: list[str] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    resources: list[ResourceInfo] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Render the structure as readable markdown for wiki pages."""
        parts: list[str] = []

        if self.module_docstring:
            parts.append(self.module_docstring.strip())

        if self.imports:
            parts.append("\n### Imports\n")
            parts.append(", ".join(f"`{i}`" for i in self.imports[:30]))

        if self.classes:
            parts.append("\n### Types\n")
            for cls in self.classes:
                bases = f"({', '.join(cls.bases)})" if cls.bases else ""
                parts.append(f"**`{cls.name}{bases}`**")
                if cls.docstring:
                    parts.append(f": {cls.docstring.split(chr(10))[0]}")
                parts.append("")
                for m in cls.methods:
                    parts.append(f"- `{_format_signature(m)}`")
                parts.append("")

        if self.functions:
            parts.append("\n### Functions\n")
            for fn in self.functions:
                parts.append(f"- `{_format_signature(fn)}`")
                if fn.docstring:
                    parts.append(f"  {fn.docstring.split(chr(10))[0]}")

        if self.resources:
            parts.append("\n### Resources\n")
            for res in self.resources:
                attrs = ", ".join(f"{k}={v}" for k, v in list(res.attributes.items())[:5])
                parts.append(f"- **{res.kind}** `{res.name}`")
                if attrs:
                    parts.append(f"  {attrs}")

        return "\n".join(parts)

    def to_beliefs(self, topic: str, wiki_path: str) -> list[dict[str, str]]:
        """Generate belief dicts from the extracted structure."""
        beliefs: list[dict[str, str]] = []
        fn_ids = ["1"]  # reference the source file footnote

        for cls in self.classes:
            stmt = f"Module defines {cls.name}"
            if cls.bases:
                stmt += f" extending {', '.join(cls.bases)}"
            beliefs.append({
                "statement": stmt[:500],
                "topic": topic,
                "subject": cls.name,
                "predicate": "is_a",
                "object": "type",
                "footnote_ids": fn_ids,
                "source_kind": "code",
            })

        for fn in self.functions:
            beliefs.append({
                "statement": f"Module defines {fn.name}({', '.join(p.name for p in fn.params)})"[:500],
                "topic": topic,
                "subject": fn.name,
                "predicate": "is_a",
                "object": "function",
                "footnote_ids": fn_ids,
                "source_kind": "code",
            })

        for res in self.resources:
            beliefs.append({
                "statement": f"Defines {res.kind} resource {res.name}"[:500],
                "topic": topic,
                "subject": res.name,
                "predicate": "is_a",
                "object": res.kind,
                "footnote_ids": fn_ids,
                "source_kind": "code",
            })

        for imp in self.imports[:20]:
            beliefs.append({
                "statement": f"Module depends on {imp}"[:500],
                "topic": topic,
                "subject": topic,
                "predicate": "depends_on",
                "object": imp,
                "footnote_ids": fn_ids,
                "source_kind": "code",
            })

        return beliefs


# --- Language registry ---

LANG_EXTENSIONS: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".tf": "terraform", ".tfvars": "terraform",
    ".yml": "yaml", ".yaml": "yaml",
}

# Ansible detection: YAML files in specific paths
_ANSIBLE_PATH_MARKERS = {"tasks", "handlers", "roles", "playbooks", "plays"}


def detect_language(suffix: str) -> str | None:
    """Detect language from file extension. Returns None if unsupported."""
    return LANG_EXTENSIONS.get(suffix.lower())


def extract_structure(source: str, language: str) -> CodeStructure | None:
    """Extract code structure for a supported language."""
    extractor = _EXTRACTORS.get(language)
    if not extractor:
        return None
    try:
        return extractor(source)
    except Exception:
        return None


# --- Python (stdlib ast) ---

def _extract_python(source: str) -> CodeStructure:
    tree = ast.parse(source)
    s = CodeStructure(language="python", module_docstring=ast.get_docstring(tree) or "")

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            s.imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            s.imports.append(node.module or "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            s.functions.append(_py_func(node))
        elif isinstance(node, ast.ClassDef):
            s.classes.append(_py_class(node))
    return s


def _py_func(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionInfo:
    params = [
        ParamInfo(name=a.arg, annotation=ast.unparse(a.annotation) if a.annotation else "")
        for a in node.args.args if a.arg not in ("self", "cls")
    ]
    return FunctionInfo(
        name=node.name, params=params,
        return_type=ast.unparse(node.returns) if node.returns else "",
        docstring=ast.get_docstring(node) or "",
        decorators=[ast.unparse(d) for d in node.decorator_list],
        line=node.lineno,
    )


def _py_class(node: ast.ClassDef) -> ClassInfo:
    methods = [_py_func(c) for c in node.body if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for m in methods:
        m.is_method = True
    return ClassInfo(
        name=node.name, bases=[ast.unparse(b) for b in node.bases],
        docstring=ast.get_docstring(node) or "", methods=methods,
        decorators=[ast.unparse(d) for d in node.decorator_list],
        line=node.lineno,
    )


# --- TypeScript / JavaScript ---

_TS_FUNC = re.compile(
    r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*"
    r"(?:<[^>]*>)?"  # generics
    r"\(([^)]*)\)"   # params
    r"(?:\s*:\s*(\S+))?",  # return type
    re.MULTILINE,
)
_TS_CLASS = re.compile(
    r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)"
    r"(?:\s+extends\s+(\w+))?"
    r"(?:\s+implements\s+([\w,\s]+))?",
    re.MULTILINE,
)
_TS_INTERFACE = re.compile(
    r"^(?:export\s+)?interface\s+(\w+)"
    r"(?:\s+extends\s+([\w,\s]+))?",
    re.MULTILINE,
)
_TS_TYPE = re.compile(r"^(?:export\s+)?type\s+(\w+)", re.MULTILINE)
_TS_IMPORT = re.compile(r"^import\s+.*?from\s+['\"]([^'\"]+)['\"]", re.MULTILINE)


def _extract_typescript(source: str) -> CodeStructure:
    s = CodeStructure(language="typescript")
    s.imports = _TS_IMPORT.findall(source)

    for m in _TS_FUNC.finditer(source):
        params = [ParamInfo(name=p.strip().split(":")[0].strip())
                  for p in m.group(2).split(",") if p.strip()]
        s.functions.append(FunctionInfo(
            name=m.group(1), params=params,
            return_type=m.group(3) or "", line=source[:m.start()].count("\n") + 1,
        ))

    for m in _TS_CLASS.finditer(source):
        bases = []
        if m.group(2):
            bases.append(m.group(2))
        if m.group(3):
            bases.extend(b.strip() for b in m.group(3).split(","))
        s.classes.append(ClassInfo(
            name=m.group(1), bases=bases,
            line=source[:m.start()].count("\n") + 1,
        ))

    for m in _TS_INTERFACE.finditer(source):
        bases = [b.strip() for b in m.group(2).split(",")] if m.group(2) else []
        s.classes.append(ClassInfo(
            name=m.group(1), bases=bases, docstring="interface",
            line=source[:m.start()].count("\n") + 1,
        ))

    for m in _TS_TYPE.finditer(source):
        s.classes.append(ClassInfo(
            name=m.group(1), docstring="type alias",
            line=source[:m.start()].count("\n") + 1,
        ))
    return s


def _extract_javascript(source: str) -> CodeStructure:
    s = _extract_typescript(source)
    s.language = "javascript"
    return s


# --- Rust ---

_RS_FN = re.compile(
    r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)"
    r"(?:<[^>]*>)?"
    r"\(([^)]*)\)"
    r"(?:\s*->\s*(\S+))?",
    re.MULTILINE,
)
_RS_STRUCT = re.compile(
    r"^(?:pub(?:\([^)]*\))?\s+)?struct\s+(\w+)", re.MULTILINE
)
_RS_ENUM = re.compile(
    r"^(?:pub(?:\([^)]*\))?\s+)?enum\s+(\w+)", re.MULTILINE
)
_RS_TRAIT = re.compile(
    r"^(?:pub(?:\([^)]*\))?\s+)?trait\s+(\w+)", re.MULTILINE
)
_RS_IMPL = re.compile(
    r"^impl(?:<[^>]*>)?\s+(?:(\w+)\s+for\s+)?(\w+)", re.MULTILINE
)
_RS_USE = re.compile(r"^use\s+([\w:]+)", re.MULTILINE)


def _extract_rust(source: str) -> CodeStructure:
    s = CodeStructure(language="rust")
    # Module doc comment
    doc_lines = []
    for line in source.split("\n"):
        if line.startswith("//!"):
            doc_lines.append(line[3:].strip())
        elif line.strip() and not line.startswith("//"):
            break
    s.module_docstring = "\n".join(doc_lines)

    s.imports = [m.replace("::", ".") for m in _RS_USE.findall(source)]

    for m in _RS_FN.finditer(source):
        params = [ParamInfo(name=p.strip().split(":")[0].strip())
                  for p in m.group(2).split(",")
                  if p.strip() and not p.strip().startswith("&self") and not p.strip().startswith("self")]
        s.functions.append(FunctionInfo(
            name=m.group(1), params=params, return_type=m.group(3) or "",
            line=source[:m.start()].count("\n") + 1,
        ))

    for m in _RS_STRUCT.finditer(source):
        s.classes.append(ClassInfo(name=m.group(1), docstring="struct",
                                   line=source[:m.start()].count("\n") + 1))
    for m in _RS_ENUM.finditer(source):
        s.classes.append(ClassInfo(name=m.group(1), docstring="enum",
                                   line=source[:m.start()].count("\n") + 1))
    for m in _RS_TRAIT.finditer(source):
        s.classes.append(ClassInfo(name=m.group(1), docstring="trait",
                                   line=source[:m.start()].count("\n") + 1))
    return s


# --- Go ---

_GO_FUNC = re.compile(
    r"^func\s+(?:\([^)]+\)\s+)?(\w+)\(([^)]*)\)(?:\s+(\S+))?", re.MULTILINE
)
_GO_TYPE_STRUCT = re.compile(r"^type\s+(\w+)\s+struct\b", re.MULTILINE)
_GO_TYPE_INTERFACE = re.compile(r"^type\s+(\w+)\s+interface\b", re.MULTILINE)
_GO_IMPORT = re.compile(r'"([^"]+)"')
_GO_PACKAGE = re.compile(r"^package\s+(\w+)", re.MULTILINE)


def _extract_go(source: str) -> CodeStructure:
    s = CodeStructure(language="go")
    pkg = _GO_PACKAGE.search(source)
    if pkg:
        s.module_docstring = f"package {pkg.group(1)}"

    # Parse import block
    import_block = re.search(r"^import\s*\((.*?)\)", source, re.MULTILINE | re.DOTALL)
    if import_block:
        s.imports = _GO_IMPORT.findall(import_block.group(1))
    else:
        single = re.findall(r'^import\s+"([^"]+)"', source, re.MULTILINE)
        s.imports = single

    for m in _GO_FUNC.finditer(source):
        params = [ParamInfo(name=p.strip().split(" ")[0])
                  for p in m.group(2).split(",") if p.strip()]
        s.functions.append(FunctionInfo(
            name=m.group(1), params=params, return_type=m.group(3) or "",
            line=source[:m.start()].count("\n") + 1,
        ))

    for m in _GO_TYPE_STRUCT.finditer(source):
        s.classes.append(ClassInfo(name=m.group(1), docstring="struct",
                                   line=source[:m.start()].count("\n") + 1))
    for m in _GO_TYPE_INTERFACE.finditer(source):
        s.classes.append(ClassInfo(name=m.group(1), docstring="interface",
                                   line=source[:m.start()].count("\n") + 1))
    return s


# --- YAML ---

def _extract_yaml(source: str) -> CodeStructure:
    import yaml
    s = CodeStructure(language="yaml")

    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError:
        return s
    if not isinstance(data, dict):
        return s

    # Check for Ansible patterns
    if _looks_like_ansible(data, source):
        return _extract_ansible_from_data(data, source)

    # Generic YAML: extract top-level keys as resources
    for key, value in data.items():
        attrs = {}
        if isinstance(value, dict):
            attrs = {k: str(v)[:80] for k, v in list(value.items())[:5]}
        elif isinstance(value, list):
            attrs = {"items": str(len(value))}
        s.resources.append(ResourceInfo(kind="key", name=str(key), attributes=attrs))
    return s


def _looks_like_ansible(data: dict[str, Any], source: str) -> bool:
    ansible_keys = {"tasks", "handlers", "roles", "vars", "hosts", "become", "gather_facts"}
    return bool(ansible_keys & set(data.keys()))


# --- Ansible ---

def _extract_ansible(source: str) -> CodeStructure:
    import yaml
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError:
        return CodeStructure(language="ansible")
    if isinstance(data, list):
        data = {"plays": data}
    if not isinstance(data, dict):
        return CodeStructure(language="ansible")
    return _extract_ansible_from_data(data, source)


def _extract_ansible_from_data(data: dict[str, Any], source: str) -> CodeStructure:
    s = CodeStructure(language="ansible")

    # Extract tasks
    tasks = data.get("tasks", [])
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            name = task.get("name", "unnamed")
            module = next((k for k in task if k not in ("name", "when", "register", "tags", "become", "vars", "notify")), "unknown")
            s.resources.append(ResourceInfo(kind="task", name=name, attributes={"module": module}))

    # Extract handlers
    handlers = data.get("handlers", [])
    if isinstance(handlers, list):
        for h in handlers:
            if isinstance(h, dict):
                s.resources.append(ResourceInfo(kind="handler", name=h.get("name", "unnamed")))

    # Extract roles
    roles = data.get("roles", [])
    if isinstance(roles, list):
        for role in roles:
            role_name = role if isinstance(role, str) else role.get("role", str(role)) if isinstance(role, dict) else str(role)
            s.imports.append(role_name)

    # Extract vars
    for var_key in ("vars", "defaults"):
        vs = data.get(var_key, {})
        if isinstance(vs, dict):
            for k in vs:
                s.resources.append(ResourceInfo(kind="variable", name=k))

    s.module_docstring = f"Ansible: {len(s.resources)} resource(s), {len(s.imports)} role(s)"
    return s


# --- Terraform (HCL) ---

_TF_RESOURCE = re.compile(r'^resource\s+"(\w+)"\s+"(\w+)"', re.MULTILINE)
_TF_DATA = re.compile(r'^data\s+"(\w+)"\s+"(\w+)"', re.MULTILINE)
_TF_VARIABLE = re.compile(r'^variable\s+"(\w+)"', re.MULTILINE)
_TF_OUTPUT = re.compile(r'^output\s+"(\w+)"', re.MULTILINE)
_TF_MODULE = re.compile(r'^module\s+"(\w+)"', re.MULTILINE)
_TF_PROVIDER = re.compile(r'^provider\s+"(\w+)"', re.MULTILINE)


def _extract_terraform(source: str) -> CodeStructure:
    # Try python-hcl2 for proper parsing
    try:
        import io

        import hcl2
        return _extract_terraform_hcl2(source)
    except ImportError:
        pass
    return _extract_terraform_patterns(source)


def _extract_terraform_hcl2(source: str) -> CodeStructure:
    import io

    import hcl2

    s = CodeStructure(language="terraform")
    data = hcl2.load(io.StringIO(source))

    for res_list in data.get("resource", []):
        for res_type, instances in res_list.items():
            for name in instances:
                s.resources.append(ResourceInfo(kind=res_type, name=name))

    for data_list in data.get("data", []):
        for data_type, instances in data_list.items():
            for name in instances:
                s.resources.append(ResourceInfo(kind=f"data.{data_type}", name=name))

    for var_list in data.get("variable", []):
        for name in var_list:
            s.resources.append(ResourceInfo(kind="variable", name=name))

    for out_list in data.get("output", []):
        for name in out_list:
            s.resources.append(ResourceInfo(kind="output", name=name))

    for mod_list in data.get("module", []):
        for name, config in mod_list.items():
            source_url = config.get("source", [""])[0] if isinstance(config.get("source"), list) else str(config.get("source", ""))
            s.imports.append(source_url or name)
            s.resources.append(ResourceInfo(kind="module", name=name, attributes={"source": source_url}))

    for prov_list in data.get("provider", []):
        for name in prov_list:
            s.imports.append(name)

    s.module_docstring = f"Terraform: {len(s.resources)} resource(s)"
    return s


def _extract_terraform_patterns(source: str) -> CodeStructure:
    """Fallback pattern extraction when python-hcl2 is not installed."""
    s = CodeStructure(language="terraform")

    for m in _TF_RESOURCE.finditer(source):
        s.resources.append(ResourceInfo(kind=m.group(1), name=m.group(2),
                                        line=source[:m.start()].count("\n") + 1))
    for m in _TF_DATA.finditer(source):
        s.resources.append(ResourceInfo(kind=f"data.{m.group(1)}", name=m.group(2),
                                        line=source[:m.start()].count("\n") + 1))
    for m in _TF_VARIABLE.finditer(source):
        s.resources.append(ResourceInfo(kind="variable", name=m.group(1),
                                        line=source[:m.start()].count("\n") + 1))
    for m in _TF_OUTPUT.finditer(source):
        s.resources.append(ResourceInfo(kind="output", name=m.group(1),
                                        line=source[:m.start()].count("\n") + 1))
    for m in _TF_MODULE.finditer(source):
        s.imports.append(m.group(1))
        s.resources.append(ResourceInfo(kind="module", name=m.group(1),
                                        line=source[:m.start()].count("\n") + 1))
    for m in _TF_PROVIDER.finditer(source):
        s.imports.append(m.group(1))

    s.module_docstring = f"Terraform: {len(s.resources)} resource(s)"
    return s


# --- Helpers ---

def _format_signature(fn: FunctionInfo) -> str:
    params = ", ".join(
        f"{p.name}: {p.annotation}" if p.annotation else p.name
        for p in fn.params
    )
    ret = f" -> {fn.return_type}" if fn.return_type else ""
    return f"{fn.name}({params}){ret}"


_EXTRACTORS: dict[str, Callable[[str], CodeStructure]] = {
    "python": _extract_python,
    "typescript": _extract_typescript,
    "javascript": _extract_javascript,
    "rust": _extract_rust,
    "go": _extract_go,
    "yaml": _extract_yaml,
    "ansible": _extract_ansible,
    "terraform": _extract_terraform,
}
