import importlib
from pathlib import Path
import sys
import pendragon

def load_plugins():
    """Dynamically loads all modules in the plugins directory and subdirectories."""
    package_root = Path(pendragon.__file__).parent
    plugins_dir = package_root / "plugins"

    if not plugins_dir.exists():
        return

    for file_path in plugins_dir.rglob("*.py"):
        if file_path.name == "__init__.py":
            continue

        relative_path = file_path.relative_to(plugins_dir)

        module_parts = list(relative_path.parts[:-1]) + [relative_path.stem]
        module_path = ".".join(module_parts)

        module_name = f"pendragon.plugins.{module_path}"

        try:
            importlib.import_module(module_name)
        except Exception as e:
            print(f"Warning: Failed to load plugin '{relative_path}': {e}",
                  file=sys.stderr)


