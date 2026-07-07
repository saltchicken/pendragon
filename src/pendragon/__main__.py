from pendragon.core import load_plugins
from pendragon.core import OPERATION_REGISTRY


def main():
    load_plugins()
    op_info = OPERATION_REGISTRY.get("image_mask")
    if op_info:
        plugin_instance = op_info["class"]()
        print(plugin_instance)
        config_class = op_info["config"]
        print(config_class)


if __name__ == "__main__":
    main()
