"""Package exports and compatibility shims for Bintu.

This module makes the public Bintu package surface explicit and keeps legacy imports stable while the modular architecture is being adopted.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

# Test suite for the Bintu scraping API.
#
# Run the whole suite from the project root:
#     python -m unittest discover -s tests -t . -p test_*.py

# -t . keeps the project root on sys.path so bintu_api and main import cleanly.
# The folder is a package so discovery recurses into it on every Python version.
# See .github/workflows/tests.yml for the command CI runs.


