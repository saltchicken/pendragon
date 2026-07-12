from pydantic import Field
from .registry import BasePluginConfig

class CenteredPluginConfig(BasePluginConfig):
    """Base config for generators that originate from a specific point."""
    center_x: float | None = Field(
        default=None,
        description="X coordinate of the pattern center. Defaults to centroid.")
    center_y: float | None = Field(
        default=None,
        description="Y coordinate of the pattern center. Defaults to centroid.")
    group_boundaries: bool = Field(
        default=False,
        description="If true, generates a single pattern globally centered across all boundaries."
    )
