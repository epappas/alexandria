"""AST-based code structure extraction.

Parses source code into structured representations — functions, classes,
imports, docstrings — without needing an LLM. The extracted structure
feeds into beliefs and enriches wiki pages with queryable facts.

Python uses stdlib ``ast``. Other languages can be added by implementing
``_extract_<lang>`` and registering in ``EXTRACTORS``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParamInfo:
    """A function parameter."""

    name: str
    annotation: str = ""
    default: str = ""


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
    """Extracted class definition."""

    name: str
    bases: list[str] = field(default_factory=list)
    docstring: str = ""
    methods: list[FunctionInfo] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    line: int = 0


@dataclass
class CodeStructure:
    """Complete structural representation of a source file."""

    language: str
    module_docstring: str = ""
    imports: list[str] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Render the structure as readable markdown for wiki pages."""
        parts: list[str] = []

        if self.module_docstring:
            parts.append(self.module_docstring.strip())

        if self.imports:
            parts.append("### Imports\n")
            parts.append(", ".join(f"`{i}`" for i in self.imports[:30]))

        if self.classes:
            parts.append("\n### Classes\n")
            for cls in self.classes:
                bases = f"({', '.join(cls.bases)})" if cls.bases else ""
                parts.append(f"**`{cls.name}{bases}`**")
                if cls.docstring:
                    parts.append(f": {cls.docstring.split(chr(10))[0]}")
                parts.append("")
                for m in cls.methods:
                    sig = _format_signature(m)
                    parts.append(f"- `{sig}`")
                    if m.docstring:
                        parts.append(f"  {m.docstring.split(chr(10))[0]}")
                parts.append("")

        if self.functions:
            parts.append("### Functions\n")
            for fn in self.functions:
                sig = _format_signature(fn)
                parts.append(f"- `{sig}`")
                if fn.docstring:
                    parts.append(f"  {fn.docstring.split(chr(10))[0]}")

        return "\n".join(parts)

    def to_beliefs(self, topic: str, wiki_path: str) -> list[dict[str, str]]:
        """Generate belief dicts from the extracted structure."""
        beliefs: list[dict[str, str]] = []

        for cls in self.classes:
            stmt = f"Module defines class {cls.name}"
            if cls.bases:
                stmt += f" inheriting from {', '.join(cls.bases)}"
            beliefs.append({
                "statement": stmt[:500],
                "topic": topic,
                "subject": cls.name,
                "predicate": "is_a",
                "object": "class",
            })
            for method in cls.methods:
                beliefs.append({
                    "statement": f"{cls.name}.{method.name} accepts {len(method.params)} parameter(s)"[:500],
                    "topic": topic,
                    "subject": f"{cls.name}.{method.name}",
                    "predicate": "is_a",
                    "object": "method",
                })

        for fn in self.functions:
            beliefs.append({
                "statement": f"Module defines function {fn.name} with {len(fn.params)} parameter(s)"[:500],
                "topic": topic,
                "subject": fn.name,
                "predicate": "is_a",
                "object": "function",
            })

        for imp in self.imports[:20]:
            beliefs.append({
                "statement": f"Module depends on {imp}"[:500],
                "topic": topic,
                "subject": topic,
                "predicate": "depends_on",
                "object": imp,
            })

        return beliefs


# Language -> extractor mapping
LANG_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
}


def detect_language(suffix: str) -> str | None:
    """Detect language from file extension. Returns None if unsupported."""
    return LANG_EXTENSIONS.get(suffix.lower())


def extract_structure(source: str, language: str) -> CodeStructure | None:
    """Extract code structure for a supported language.

    Returns None if the language is unsupported or parsing fails.
    """
    extractor = _EXTRACTORS.get(language)
    if not extractor:
        return None
    try:
        return extractor(source)
    except SyntaxError:
        return None


# --- Python extractor ---


def _extract_python(source: str) -> CodeStructure:
    """Extract structure from Python source using stdlib ast."""
    tree = ast.parse(source)

    structure = CodeStructure(language="python")
    structure.module_docstring = ast.get_docstring(tree) or ""

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                structure.imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            structure.imports.append(module)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            structure.functions.append(_parse_function(node))
        elif isinstance(node, ast.ClassDef):
            structure.classes.append(_parse_class(node))

    return structure


def _parse_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionInfo:
    """Parse a function/method definition node."""
    params: list[ParamInfo] = []
    for arg in node.args.args:
        if arg.arg == "self" or arg.arg == "cls":
            continue
        ann = ast.unparse(arg.annotation) if arg.annotation else ""
        params.append(ParamInfo(name=arg.arg, annotation=ann))

    ret = ast.unparse(node.returns) if node.returns else ""
    decorators = [ast.unparse(d) for d in node.decorator_list]

    return FunctionInfo(
        name=node.name,
        params=params,
        return_type=ret,
        docstring=ast.get_docstring(node) or "",
        decorators=decorators,
        line=node.lineno,
    )


def _parse_class(node: ast.ClassDef) -> ClassInfo:
    """Parse a class definition node."""
    bases = [ast.unparse(b) for b in node.bases]
    decorators = [ast.unparse(d) for d in node.decorator_list]

    methods: list[FunctionInfo] = []
    for child in node.body:
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            fn = _parse_function(child)
            fn.is_method = True
            methods.append(fn)

    return ClassInfo(
        name=node.name,
        bases=bases,
        docstring=ast.get_docstring(node) or "",
        methods=methods,
        decorators=decorators,
        line=node.lineno,
    )


def _format_signature(fn: FunctionInfo) -> str:
    """Format a function signature for display."""
    params = ", ".join(
        f"{p.name}: {p.annotation}" if p.annotation else p.name
        for p in fn.params
    )
    ret = f" -> {fn.return_type}" if fn.return_type else ""
    return f"{fn.name}({params}){ret}"


_EXTRACTORS: dict[str, any] = {
    "python": _extract_python,
}
