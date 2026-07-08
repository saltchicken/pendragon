# src/pendragon/__main__.py

import argparse
import sys

from loguru import logger
import yaml

from pendragon.core import load_plugins

from .engine import PendragonEngine


logger.remove()
logger.add(
    sys.stderr,
    format=(
        "<green>{module: <20}</green>."
        "<green>{function: <20}</green> | "
        "<level>{level: <8}</level> | "
        "{message}"
    )
)

def main():
    parser = argparse.ArgumentParser(
        description="Pendragon CNC G-code generator.")
    parser.add_argument("recipe",
                        type=str,
                        help="Path to the YAML recipe file.")
    parser.add_argument("--output",
                        type=str,
                        default="output.nc",
                        help="Output path for the generated G-code.")
    parser.add_argument("--no-vis",
                        action="store_true",
                        help="Disable the Vispy visualization window.")
    args = parser.parse_args()

    # 1. Discover and load plugins
    load_plugins()

    # 2. Load user recipe
    try:
        with open(args.recipe, 'r') as f:
            raw_user_recipe = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Recipe file not found: {args.recipe}")
        sys.exit(1)
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file: {e}")
        sys.exit(1)

    if not isinstance(raw_user_recipe, list):
        logger.error(
            "Invalid recipe format: The YAML file must contain a list of operations."
        )
        sys.exit(1)

    # 3. Initialize Orchestrator
    engine = PendragonEngine(recipe=raw_user_recipe)

    # 4. Build Pipeline
    if not engine.build_pipeline():
        logger.error(
            "Pipeline construction failed due to validation errors. Exiting.")
        sys.exit(1)

    # 5. Execute
    final_lines = engine.run()
    logger.success(
        f"Pipeline complete. Generated {len(final_lines)} final lines.")

    # 6. Export
    engine.export_gcode(lines=final_lines, output_path=args.output)

    # 7. Visualize (Optional)
    if not args.no_vis:
        engine.visualize()


if __name__ == "__main__":
    main()
