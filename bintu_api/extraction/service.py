"""Extraction service boundary for REST and MCP consumers.

This module is the intended stable entry point for the shared
fetch -> robots -> cache -> extract orchestration. During the modularization
migration, it re-exports the existing implementation from the route layer so
existing tests and callers retain their exact behavior and patch points.

Important boundaries, invariants, or compatibility notes:
- Do not add extraction, metering, or MCP formatting logic here yet.
- Preserve the existing ``bintu_api.api.routes.common._fetch_and_extract``
  compatibility seam until all callers and tests have migrated.
"""

def __getattr__(name: str):
    from bintu_api.api.routes import common

    return getattr(common, name)
