# Test suite for the Bintu scraping API.
#
# Run the whole suite from the project root:
#     python -m unittest discover -s tests -t . -p test_*.py

# -t . keeps the project root on sys.path so bintu_api and main import cleanly.
# The folder is a package so discovery recurses into it on every Python version.
# See .github/workflows/tests.yml for the command CI runs.
