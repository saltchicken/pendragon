from typing import List

from loguru import logger
from shapely.geometry import LineString

from pendragon.pen import PenConfig
from pendragon.pen import PenTool


def export_gcode(lines: list[LineString], output_filename: str = "output.nc"):
    """Handles the writing of G-code paths to a file."""
    if not lines:
        logger.warning("No lines to export!")
        return

    logger.info(f"Generating G-code to {output_filename}...")
    config = PenConfig()
    with PenTool(config=config, output_filename=output_filename) as pen:
        for line in lines:
            pen.draw_path(list(line.coords))
