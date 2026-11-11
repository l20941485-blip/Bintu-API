"""Guard the shared HTTP scrape adapter against REST route dependencies."""

import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "relative_path",
    [
        "api/scrape_adapter.py",
        "mcp/http_api.py",
        "mcp/streamable.py",
    ],
)
def test_shared_scrape_consumers_do_not_import_rest_routes(relative_path):
    package_root = Path(__file__).resolve().parents[2] / "bintu_api"
    path = package_root / relative_path
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


def test_old_route_common_module_stays_removed():
    package_root = Path(__file__).resolve().parents[2] / "bintu_api"

    assert not (package_root / "api" / "routes" / "common.py").exists()
