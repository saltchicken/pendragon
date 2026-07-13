from dataclasses import dataclass
from typing import Optional, Tuple

from gscrib import GCodeBuilder
from loguru import logger


@dataclass
class PenConfig:
    clearance_z: float = 5.0
    rapid_z: float = 1.0
    feed_rate: float = 400.0
    down_z: float = -1.0


class PenTool:
    """Context manager for handling G-code generation state and tool movements."""

    def __init__(self,
                 config: PenConfig,
                 output_filename: str = "output.nc") -> None:
        self.g = GCodeBuilder(output=output_filename)
        self.config = config
        self.output_filename = output_filename  # Store for use in __exit__
        self.current_z: Optional[float] = None

    def __enter__(self) -> "PenTool":
        self._build_preamble()
        return self

    def __exit__(self, exc_type: type, exc_val: Exception,
                 exc_tb: type) -> None:
        self.tool_off(clearance=True)
        self._build_postamble()
        self.g.flush()

        # Only log success stats if no exception caused the exit
        if exc_type is None:
            try:
                with open(self.output_filename, 'r') as f:
                    logger.info(
                        f"Total G-code lines produced: {sum(1 for _ in f)}")
            except Exception as e:
                logger.warning(f"Could not count lines in output file: {e}")

            logger.info(f"G-code successfully saved to {self.output_filename}")

    def _build_preamble(self) -> None:
        self.g.set_plane('xy')
        self.g.set_distance_mode('absolute')
        self.g.set_length_units('mm')
        self.g.write("G54")
        self.g.write(f"F{self.config.feed_rate}")
        self.g.rapid(z=self.config.clearance_z)
        self.current_z = self.config.clearance_z

    def _build_postamble(self) -> None:
        self.g.write("M5")
        self.g.write("G17 G90")
        self.g.write("M2")

    def move_to(self, x: float, y: float, clearance: bool = False) -> None:
        self.tool_off(clearance=clearance)
        self.g.rapid(x=x, y=y)

    def tool_on(self) -> None:
        if self.current_z != self.config.down_z:
            self.g.move(z=self.config.down_z)
            self.current_z = self.config.down_z

    def tool_off(self, clearance: bool = False) -> None:
        target_z = self.config.clearance_z if clearance else self.config.rapid_z
        if self.current_z is None or self.current_z < target_z:
            self.g.rapid(z=target_z)
            self.current_z = target_z

    def draw_path(self,
                  points: list[Tuple[float, float]],
                  clearance: bool = False) -> None:
        if not points:
            return
        self.move_to(*points[0], clearance=clearance)
        self.tool_on()
        for x, y in points[1:]:
            self.g.move(x=x, y=y, f=self.config.feed_rate)
        self.tool_off(clearance=False)
