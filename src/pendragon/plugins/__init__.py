import importlib
import pkgutil


def load_plugins() -> None:
    """Dynamically loads all plugins in the pendragon.plugins directory tree."""
    try:
        import pendragon.plugins
    except ImportError:
        return

    for _, name, is_pkg in pkgutil.walk_packages(pendragon.plugins.__path__,
                                                 pendragon.plugins.__name__ + "."):
        if not is_pkg:
            importlib.import_module(name)
