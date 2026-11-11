"""Guard reader routes against dependencies on REST scrape routes."""

import ast
from pathlib import Path


def test_reader_routes_do_not_import_api_routes():
    path = (
        Path(__file__).resolve().parents[2]
        / "bintu_api"
        / "reader"
        / "routes.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module != "bintu_api.api.routes"
            assert not module.startswith("bintu_api.api.routes.")
            if module == "bintu_api.api":
                assert all(alias.name != "routes" for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "bintu_api.api.routes"
                assert not alias.name.startswith("bintu_api.api.routes.")
