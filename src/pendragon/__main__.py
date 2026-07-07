import argparse
import yaml
from loguru import logger
from shapely.geometry import Polygon

from pendragon.core import load_plugins
from pendragon.core import OPERATION_REGISTRY
from pendragon.core import PipelineState
from pendragon.core import PipelineRunner


def main():
    # Set up argument parsing for the CLI
    parser = argparse.ArgumentParser(description="Pendragon CNC G-code generator.")
    parser.add_argument("recipe", type=str, help="Path to the YAML recipe file.")
    args = parser.parse_args()

    # 1. Discover and load all plugins
    load_plugins()
    
    # 2. Load user recipe from the YAML file
    try:
        with open(args.recipe, 'r') as f:
            raw_user_recipe = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Recipe file not found: {args.recipe}")
        return
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file: {e}")
        return

    if not isinstance(raw_user_recipe, list):
        logger.error("Invalid recipe format: The YAML file must contain a list of operations.")
        return
    
    # 3. Initialize the Runner
    dummy_boundary = Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    initial_state = PipelineState(boundary=dummy_boundary, operation_name="base_geometry")
    runner = PipelineRunner(initial_state)

    # 4. Construct the pipeline sequence
    for step in raw_user_recipe:
        op_name = step.get("operation")
        if not op_name:
            logger.error(f"Invalid step configuration, missing 'operation' key: {step}")
            continue

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
