"""Guard the completed top-level package cleanup."""

from pathlib import Path


def test_package_root_contains_only_approved_python_modules():
    package_root = Path(__file__).resolve().parents[2] / "bintu_api"

    actual = {path.name for path in package_root.glob("*.py")}
    expected = {"__init__.py", "settings.py"}

    assert actual == expected, (
        f"Unexpected root modules: {sorted(actual - expected)}; "
        f"missing expected modules: {sorted(expected - actual)}. "
        "Place new implementation modules in their owning package, "
        "or explicitly review and update this boundary."
    )


def test_removed_mcp_legacy_module_stays_removed():
    package_root = Path(__file__).resolve().parents[2] / "bintu_api"

    assert not (package_root / "mcp" / "legacy.py").exists(), (
        "MCP exports now belong to the canonical package modules; "
        "do not restore the removed legacy module."
    )
