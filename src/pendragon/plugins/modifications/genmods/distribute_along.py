from typing import Any, Dict, Optional

from loguru import logger
from pydantic import Field

from pendragon.engine import BasePluginConfig
from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation
from pendragon.engine.registry import OPERATION_REGISTRY


class DistributeConfig(BasePluginConfig):
    generator: str = Field(default="grid_lines",
                           description="Generator to stamp along the line.")
    spacing: float = Field(default=10.0, description="Distance between stamps.")
    generator_settings: Dict[str, Any] = Field(default_factory=dict)


@register_operation("distribute_along", config_class=DistributeConfig)
class DistributeAlongOp(PipelineOperation):

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or DistributeConfig()

        # 1. Retrieve the sub-generator
        op_info = OPERATION_REGISTRY.get(cfg.generator)
        if not op_info:
            logger.error(f"Generator {cfg.generator} not found.")
            return state

        SubGenClass = op_info["class"]
        SubConfigClass = op_info["config"]

        new_lines = []

        # 2. Walk along every existing line
        for line in state.lines:
            length = line.length
            num_stamps = int(length / cfg.spacing)

            for i in range(num_stamps):
                dist = i * cfg.spacing
                point = line.interpolate(dist)

                # 3. Create a tiny local boundary (a tiny square around the point)
                # This tricks the sub-generator into working within a local constraint
                local_boundary = point.buffer(cfg.spacing / 2)

                # 4. Run the generator for this tiny cell
                sub_config = SubConfigClass(**cfg.generator_settings)
                sub_gen = SubGenClass(config=sub_config)

                # Inject local center context
                cell_ctx = PipelineContext(local_center_x=point.x,
                                           local_center_y=point.y)

                res = sub_gen.process(PipelineState(boundary=local_boundary,
                                                    lines=[]),
                                      context=cell_ctx)
                new_lines.extend(res.lines)

        return PipelineState(boundary=state.boundary,
                             lines=state.lines + new_lines,
                             operation_name="distribute_along")
