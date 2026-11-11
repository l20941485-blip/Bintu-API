from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "bintu_api"


def _iter_python_files(package: Path) -> list[Path]:
    return sorted(package.rglob("*.py"))


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT.parent)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
            for alias in node.names:
                if alias.name:
                    modules.add(f"{node.module}.{alias.name}")

    return modules


def _assert_no_imports(source_package: str, forbidden_packages: set[str]) -> None:
    package_path = ROOT / source_package.replace(".", "/")

    for path in _iter_python_files(package_path):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        imported = _imported_modules(tree)

        violations = sorted(
            module
            for module in imported
            if any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in forbidden_packages
            )
        )

        assert not violations, (
            f"{_module_name(path)} must not import {sorted(forbidden_packages)}; "
            f"found: {violations}"
        )


def test_extraction_does_not_import_scraper() -> None:
    _assert_no_imports("extraction", {"bintu_api.scraper"})


@pytest.mark.xfail(
    reason=(
        "MCP transport still directly imports scraper and extraction internals; "
        "remove this exception during the MCP adapter migration."
    ),
    strict=True,
)
def test_mcp_does_not_directly_import_scraper_or_extraction() -> None:
    _assert_no_imports(
        "mcp",
        {"bintu_api.scraper", "bintu_api.extraction"},
    )
def test_extraction_does_not_import_api() -> None:
    _assert_no_imports("extraction", {"bintu_api.api"})
