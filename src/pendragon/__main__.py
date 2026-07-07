import argparse
import yaml
from loguru import logger
from shapely.geometry import Polygon
import matplotlib.pyplot as plt

from pendragon.core import load_plugins
from pendragon.core import OPERATION_REGISTRY
from pendragon.core import PipelineState
from pendragon.core import PipelineRunner

# Import the Pen tool components
from pendragon.pen import PenTool, PenConfig


def main():
    # Set up argument parsing for the CLI
    parser = argparse.ArgumentParser(description="Pendragon CNC G-code generator.")
    parser.add_argument("recipe", type=str, help="Path to the YAML recipe file.")
    parser.add_argument("--output", type=str, default="output.nc", help="Output path for the generated G-code.")
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
    dummy_boundary = Polygon([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)])
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

    # 7. Generate G-code
    if final_lines:
        logger.info(f"Generating G-code to {args.output}...")
        # You can override PenConfig defaults here if needed: PenConfig(feed_rate=600.0, etc.)
        pen_config = PenConfig() 
        
        with PenTool(config=pen_config, output_filename=args.output) as pen:
            for line in final_lines:
                # Extract coordinates from the Shapely LineString and pass to the pen tool
                points = list(line.coords)
                pen.draw_path(points)

        # 8. Visualization
        logger.info("Opening visualization window...")
        fig, ax = plt.subplots(figsize=(8, 8))
        
        # Plot the bounding box (optional, for context)
        bx, by = dummy_boundary.exterior.xy
        ax.plot(bx, by, color='red', linestyle='--', label='Boundary')

        # Plot each generated line
        for line in final_lines:
            x, y = line.xy
            ax.plot(x, y, color='black', linewidth=1)
            
        ax.set_aspect('equal') # Keeps the grid from looking stretched
        ax.set_title("Pendragon Generated Lines")
        plt.show()
    else:
        logger.warning("No lines to display or export!")

if __name__ == "__main__":
    main()
