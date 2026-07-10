import math
from typing import List

from loguru import logger
from pydantic import Field
from shapely import affinity
from shapely.geometry import LineString
from shapely.geometry import MultiLineString

from pendragon.core import BasePluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class ChaoticConfig(BasePluginConfig):
    spacing: float = Field(
        default=2.0, 
        gt=0.0,
        description="Spacing between the coarse baseline segments."
    )
    depth: int = Field(
        default=4, 
        ge=0,
        description="Recursion depth for the fractal generation."
    )
    chaos_freq: float = Field(
        default=0.15,
        description="Spatial frequency of the chaotic distortion."
    )
    chaos_amp: float = Field(
        default=0.8,
        description="Amplitude of the chaotic distortion."
    )


@register_operation("chaotic", config_class=ChaoticConfig)
class ChaoticFill(PipelineOperation):
    """
    Generates a highly irregular, fractal-like fill using a base motif that
    is recursively morphed using spatially-driven affine transformations.
    """

    def process(self, state: PipelineState) -> PipelineState:
        # Load configuration, falling back to defaults if missing
        cfg = self.config or ChaoticConfig()
        
        # Fetch the boundary, automatically applying any configured overscan buffer
        effective_boundary = self.get_effective_boundary(state)

        if not effective_boundary or effective_boundary.is_empty:
            logger.warning("No boundary available. Skipping chaotic fill.")
            return state

        logger.info(
            f"Generating chaotic fill (depth={cfg.depth}, spacing={cfg.spacing}) "
            f"over the bounding area..."
        )

        minx, miny, maxx, maxy = effective_boundary.bounds
        coarse_spacing = max(cfg.spacing * 4.0, 1.0)
        base_lines = []
        y = miny - coarse_spacing
        left_to_right = True

        # 1. Generate coarse zig-zag baseline
        while y <= maxy + coarse_spacing:
            x1, x2 = (minx - coarse_spacing, maxx + coarse_spacing) if left_to_right else (maxx + coarse_spacing, minx - coarse_spacing)
            base_lines.append(LineString([(x1, y), (x2, y)]))
            y += coarse_spacing
            left_to_right = not left_to_right

        pts = []
        for line in base_lines:
            pts.extend(list(line.coords))
        base_path = LineString(pts)

        base_motif = LineString([(0, 0), (0.3, 1.0), (0.7, -0.5), (1, 0)])

        # 2. Define the recursive affine transformation
        def recursive_affine_fractal(p1, p2, current_depth, current_scale):
            if current_depth == 0:
                return [p1, p2]

            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            dist = math.hypot(dx, dy)
            
            if dist < 0.01:
                return [p1, p2]

            seg_angle = math.degrees(math.atan2(dy, dx))
            mx, my = p1[0] + dx / 2, p1[1] + dy / 2

            # Chaos math based on spatial position
            shear_x = math.sin(mx * cfg.chaos_freq) * cfg.chaos_amp
            shear_y = math.cos(my * cfg.chaos_freq) * cfg.chaos_amp
            scale_y = 1.0 + math.sin((mx + my) * (cfg.chaos_freq * 0.7)) * (cfg.chaos_amp * 0.75)

            matrix = [1.0, shear_x, shear_y, scale_y, 0.0, 0.0]
            warped_motif = affinity.affine_transform(base_motif, matrix)

            scaled = affinity.scale(warped_motif, xfact=dist, yfact=current_scale, origin=(0, 0))
            rotated = affinity.rotate(scaled, seg_angle, origin=(0, 0), use_radians=False)
            translated = affinity.translate(rotated, xoff=p1[0], yoff=p1[1])

            motif_coords = list(translated.coords)

            result_path = []
            for i in range(len(motif_coords) - 1):
                sub_path = recursive_affine_fractal(
                    motif_coords[i],
                    motif_coords[i + 1],
                    current_depth - 1,
                    current_scale * 0.5
                )
                if i > 0:
                    sub_path = sub_path[1:]
                result_path.extend(sub_path)
            
            return result_path

        # 3. Apply the recursion to the baseline
        fractal_coords = []
        coords = list(base_path.coords)
        for i in range(len(coords) - 1):
            segment_fractal = recursive_affine_fractal(
                coords[i], 
                coords[i + 1],
                cfg.depth,
                coarse_spacing * 1.5
            )
            if i > 0:
                segment_fractal = segment_fractal[1:]
            fractal_coords.extend(segment_fractal)

        raw_fractal_line = LineString(fractal_coords)

        # 4. Clip strictly to the effective boundary
        clipped_lines: List[LineString] = []
        if raw_fractal_line.intersects(effective_boundary):
            clipped = raw_fractal_line.intersection(effective_boundary)
            
            if isinstance(clipped, LineString) and not clipped.is_empty:
                clipped_lines.append(clipped)
            elif isinstance(clipped, MultiLineString):
                for sub_line in clipped.geoms:
                    if not sub_line.is_empty:
                        clipped_lines.append(sub_line)

        logger.success(f"Generated {len(clipped_lines)} bounded chaotic paths.")

        # 5. Return a new immutable PipelineState
        return PipelineState(
            boundary=state.boundary, 
            lines=state.lines + clipped_lines,
            operation_name="chaotic"
        )
