import argparse
import sys

from loguru import logger
from shapely.geometry import Polygon
import yaml

from pendragon.engine import load_plugins
from pendragon.engine import PendragonEngine
from pendragon.export import export_gcode
from pendragon.utils import load_dxf_boundary


def setup_logger():
    logger.remove()
    logger.add(sys.stderr,
               format=("<green>{module: <20}</green>."
                       "<green>{function: <20}</green> | "
                       "<level>{level: <8}</level> | "
                       "{message}"))


def run_headless(engine: PendragonEngine, output_path: str):
    """Executes the pipeline synchronously and exports the result."""
    if not engine.build_pipeline():
        logger.error(
            "Pipeline construction failed due to validation errors. Exiting.")
        sys.exit(1)

    final_lines = engine.run()
    logger.success(
        f"Pipeline complete. Generated {len(final_lines)} final lines.")
    export_gcode(final_lines, output_path)


def run_gui(engine: PendragonEngine):
    """Initializes the MVC architecture and launches the PyQt application."""
    logger.info("Opening live editor visualization window...")
    try:
        from PyQt5.QtWidgets import QApplication

        from pendragon.gui import LiveEditorWindow
        from pendragon.gui import PipelineController

        qt_app = QApplication.instance() or QApplication([])

        # 1. Initialize the Controller with our Engine
        controller = PipelineController(engine)

        # 2. Bind the View to the Controller
        editor = LiveEditorWindow(controller)
        editor.resize(1200, 800)
        editor.show()

        sys.exit(qt_app.exec_())
    except ImportError as e:
        logger.error(
            f"Failed to launch GUI: {e}. "
            "Ensure PyQt5 and vispy are installed, or run with --no-vis.")


def main():
    setup_logger()

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

    # Schema Generation Early Exit
    if args.generate_schema:
        from pendragon.engine import generate_recipe_schema
        generate_recipe_schema(args.generate_schema)
        sys.exit(0)

    load_plugins()

    # Recipe Parsing
    raw_user_recipe = []
    if args.recipe:
        try:
            with open(args.recipe, 'r') as f:
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
        logger.info("No recipe specified. Starting an empty pipeline.")

    # Boundary Setup
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

    # Initialize Engine
    is_interactive = not args.no_vis
    engine = PendragonEngine(recipe=raw_user_recipe,
                             boundary=boundary,
                             interactive=is_interactive)

    # Route Execution Mode
    if args.no_vis:
        run_headless(engine, args.output)
    else:
        run_gui(engine)
