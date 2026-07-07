from pendragon.core.registry import OPERATION_REGISTRY

import importlib
import sys
from pathlib import Path

def load_plugins():
    """Dynamically loads all modules in the plugins directory and subdirectories."""
    plugins_dir = Path(__file__).parent / "plugins"

    if not plugins_dir.exists():
        return

    # 1. Use rglob (recursive glob) to search all subfolders
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
            print(f"Warning: Failed to load plugin '{relative_path}': {e}", file=sys.stderr)


def main():
    load_plugins()
    print(OPERATION_REGISTRY)

if __name__ == "__main__":
    main()
