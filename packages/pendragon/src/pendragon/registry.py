import importlib
from pathlib import Path

from loguru import logger
from nodeweaver.registry import OperationRegistry
from nodeweaver.registry import PipelineOperation
from pydantic import BaseModel, Field
from .state import GeometryState

# 1. Instantiate the Pendragon-specific registry using the generic from nodeweaver
dxf_registry = OperationRegistry[GeometryState]()

# 2. Base Configuration
class PendragonBaseConfig(BaseModel):
    overscan: float = Field(
        default=0.0,
        description="Distance to expand/shrink the clipping boundary."
    )

# 3. Geometric-specific operations base class
class PendragonOperation(PipelineOperation[GeometryState]):
    def get_effective_boundary(self, state: GeometryState):
        overscan = getattr(self.config, 'overscan', 0.0)
        if overscan != 0.0 and state.boundary:
            return state.boundary.buffer(overscan, join_style=2)
        return state.boundary


# 3. Geometric-specific operations base class
class PendragonOperation(PipelineOperation[GeometryState]):

    def get_effective_boundary(self, state: GeometryState):
        """
        Returns the boundary, buffered by the overscan setting if applicable.
        join_style=2 (mitre) ensures square bounds maintain sharp corners.
        """
        overscan = getattr(self.config, 'overscan', 0.0)
        if overscan != 0.0 and state.boundary:
            return state.boundary.buffer(overscan, join_style=2)
        return state.boundary


# 4. Mixins
class CenteredPluginConfig(PendragonBaseConfig):
    center_x: float | None = Field(
        default=None,
        description="X coordinate of the pattern center. Defaults to centroid.")
    center_y: float | None = Field(
        default=None,
        description="Y coordinate of the pattern center. Defaults to centroid.")
    group_boundaries: bool = Field(
        default=False,
        description=
        "If true, generates a single pattern globally centered across all boundaries."
    )


# 5. Battery Loader
def load_batteries():
    """Dynamically loads all modules in the plugins directory and subdirectories."""
    plugins_dir = Path(__file__).resolve().parent / "plugins"

    if not plugins_dir.exists():
        logger.warning(f"Plugins directory not found at {plugins_dir}")
        return

    for file_path in plugins_dir.rglob("*.py"):
        if file_path.name == "__init__.py":
            continue

        relative_path = file_path.relative_to(plugins_dir)
        module_parts = list(relative_path.parts[:-1]) + [relative_path.stem]
        module_name = f"pendragon.plugins.{'.'.join(module_parts)}"

        try:
            importlib.import_module(module_name)
        except Exception as e:
            logger.warning(f"Failed to load plugin '{relative_path}': {e}")
