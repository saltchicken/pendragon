import importlib
from pathlib import Path
from loguru import logger

def load_plugins():
    """Dynamically loads all modules in the plugins directory and subdirectories."""
    # Resolve the path to `src/pendragon/` (parent of the engine directory)
    package_root = Path(__file__).resolve().parent.parent
    plugins_dir = package_root / "plugins"

    if not plugins_dir.exists():
        logger.warning(f"Plugins directory not found at {plugins_dir}")
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
            logger.warning(f"Failed to load plugin '{relative_path}': {e}")
