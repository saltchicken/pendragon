from loguru import logger
from shapely.geometry import Polygon

from pendragon.core import load_plugins
from pendragon.core import OPERATION_REGISTRY
from pendragon.core import PipelineState
from pendragon.core import PipelineRunner


def main():
    # 1. Discover and load all plugins
    load_plugins()
    
    # 2. Simulate raw user recipe with a sequence of operations
    raw_user_recipe = [
        {
            "operation": "image_mask",
            "settings": {
                "mask_image": "images/loz.jpg",
                "threshold": 0.85
            }
        }
    ]
    
    # 3. Initialize the Runner
    dummy_boundary = Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    initial_state = PipelineState(boundary=dummy_boundary, operation_name="base_geometry")
    runner = PipelineRunner(initial_state)

    # 4. Construct the pipeline sequence
    for step in raw_user_recipe:
        op_name = step["operation"]
        op_info = OPERATION_REGISTRY.get(op_name)
        
        if not op_info:
            logger.error(f"Operation '{op_name}' not found in registry.")
            continue

        PluginClass = op_info["class"]
        ConfigClass = op_info["config"]
        
        validated_config = None
        if ConfigClass:
            try:
                validated_config = ConfigClass(**step.get("settings", {}))
                logger.success(f"Successfully validated config for {op_name}")
            except Exception as e:
                logger.error(f"Configuration error for '{op_name}': {e}")
                continue
                
        # Instantiate and queue the plugin
        plugin_instance = PluginClass(config=validated_config)
        runner.add_operation(plugin_instance)

    # 5. Execute all steps chronologically
    runner.execute_all()
    
    # 6. Retrieve the final state
    final_lines = runner.get_final_lines()
    logger.success(f"Pipeline complete. Generated {len(final_lines)} final lines.")


if __name__ == "__main__":
    main()
