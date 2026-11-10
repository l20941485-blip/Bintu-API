import ast
import subprocess
import sys
from pathlib import Path

files = subprocess.check_output(
    ["git", "diff", "--name-only"],
).decode("utf-8").splitlines()

changed = []

for file in files:
    if not file.endswith(".py"):
        continue

    old_bytes = subprocess.check_output(
        ["git", "show", f"HEAD:{file}"],
    )
    old_source = old_bytes.decode("utf-8-sig")

    new_source = Path(file).read_text(encoding="utf-8-sig")

    old_tree = ast.dump(ast.parse(old_source), include_attributes=False)
    new_tree = ast.dump(ast.parse(new_source), include_attributes=False)

    if old_tree != new_tree:
        changed.append(file)

if changed:
    print("Semantic changes detected:")
    print("\n".join(changed))
    sys.exit(1)

print("No semantic AST changes detected.")