import argparse
import sys

from loguru import logger
from shapely.geometry import Polygon
import yaml

# Cleanly import from our new consolidated engine package
from pendragon.engine import PendragonEngine, load_plugins
from pendragon.utils import load_dxf_boundary
from pendragon.pen import PenConfig, PenTool

logger.remove()
logger.add(sys.stderr,
           format=("<green>{module: <20}</green>."
                   "<green>{function: <20}</green> | "
                   "<level>{level: <8}</level> | "
                   "{message}"))


def main():
    parser = argparse.ArgumentParser(
        description="Pendragon CNC G-code generator.")
    parser.add_argument("recipe",
                        type=str,
                        nargs="?",
                        default=None,
                        help="Path to the YAML recipe file (optional).")
    parser.add_argument("--output",
                        type=str,
                        default="output.nc",
                        help="Output path for the generated G-code.")
    parser.add_argument("--no-vis",
                        action="store_true",
                        help="Disable the Vispy visualization window.")
    parser.add_argument("--width",
                        type=float,
                        help="Width of the rectangular boundary.")
    parser.add_argument("--height",
                        type=float,
                        help="Height of the rectangular boundary.")
    parser.add_argument("--dxf",
                        type=str,
                        help="Path to a .dxf file to use as the boundary.")

    parser.add_argument("--generate-schema",
                        type=str,
                        metavar="PATH",
                        help="Generate JSON schema for recipes and exit.")
    args = parser.parse_args()

    if args.generate_schema:
        # Schema generator is now also housed in the engine package
        from pendragon.engine import generate_recipe_schema
        generate_recipe_schema(args.generate_schema)
        sys.exit(0)

    # 1. Discover and load plugins
    load_plugins()

    # 2. Load user recipe
    raw_user_recipe = []
    if args.recipe:
        try:
            with open(args.recipe, 'r') as f:
                # Fallback to empty list if file is completely empty
                raw_user_recipe = yaml.safe_load(f) or []
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
    else:
        logger.info(
            "No recipe specified. Starting an empty pipeline for the GUI.")

    boundary = None
    if args.dxf:
        try:
            logger.info(f"Loading boundary from DXF: {args.dxf}")
            boundary = load_dxf_boundary(args.dxf)
        except Exception as e:
            logger.error(f"Failed to load DXF boundary: {e}")
            sys.exit(1)
    elif args.width is not None and args.height is not None:
        logger.info(
            f"Using defined rectangular boundary: {args.width}x{args.height}")
        boundary = Polygon([(0, 0), (args.width, 0), (args.width, args.height),
                            (0, args.height), (0, 0)])
    else:
        logger.info("Using default 200x200 boundary.")
        boundary = Polygon([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)])

    # 3. Initialize Orchestrator
    is_interactive = not args.no_vis
    engine = PendragonEngine(recipe=raw_user_recipe,
                             boundary=boundary,
                             interactive=is_interactive)

    # 4. Build Pipeline
    if not engine.build_pipeline():
        logger.error(
            "Pipeline construction failed due to validation errors. Exiting.")
        sys.exit(1)

    # 5. Execute
    final_lines = engine.run()
    logger.success(
        f"Pipeline complete. Generated {len(final_lines)} final lines.")

    # 6. Export G-Code (Delegated from the engine back to the CLI script)
    if final_lines:
        logger.info(f"Generating G-code to {args.output}...")
        config = PenConfig()
        with PenTool(config=config, output_filename=args.output) as pen:
            for line in final_lines:
                pen.draw_path(list(line.coords))
    else:
        logger.warning("No lines to export!")

    # 7. Visualize (Optional)
    if not args.no_vis:
        logger.info("Opening live editor visualization window...")
        try:
            from PyQt5.QtWidgets import QApplication

            from pendragon.gui import LiveEditorWindow

            qt_app = QApplication.instance() or QApplication([])
            editor = LiveEditorWindow(engine)
            editor.resize(1200, 800)
            editor.show()
            qt_app.exec_()
        except ImportError as e:
            logger.error(
                f"Failed to launch GUI: {e}. "
                "Ensure PyQt5 and vispy are installed, or run with --no-vis.")


if __name__ == "__main__":
    main()
