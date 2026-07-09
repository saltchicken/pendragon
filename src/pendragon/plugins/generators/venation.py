from typing import List

from loguru import logger
import numpy as np
from pydantic import Field
from scipy.spatial import cKDTree
from shapely.geometry import LineString
from shapely.geometry import MultiLineString
from shapely.geometry import Point
from shapely.ops import linemerge

from pendragon.core import CenteredPluginConfig
from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core import register_operation


class VenationConfig(CenteredPluginConfig):
    num_leaves: int = Field(
        default=500,
        description="Number of attractor points (leaves) to drive the growth.")
    kill_distance: float = Field(
        default=2.0,
        description=
        "Distance at which an attractor is considered reached and removed.")
    attract_distance: float = Field(
        default=20.0,
        description="Maximum distance an attractor can influence a growing vein."
    )
    segment_length: float = Field(
        default=1.0, description="How far a vein grows in a single step.")
    root_x: float = Field(default=100.0,
                          description="Starting X coordinate of the root vein.")
    root_y: float = Field(default=0.0,
                          description="Starting Y coordinate of the root vein.")
    seed: int = Field(default=42,
                      description="Random seed for repeatable patterns.")
    max_iterations: int = Field(
        default=1000,
        description="Safety limit to prevent infinite generation loops.")


@register_operation("venation", config_class=VenationConfig)
class VenationGen(PipelineOperation):
    """Generates organic branching structures using the Space Colonization Algorithm."""

    def process(self, state: PipelineState) -> PipelineState:
        cfg = self.config or VenationConfig()
        boundary = self.get_effective_boundary(state)
        minx, miny, maxx, maxy = boundary.bounds

        # Check if center_x and center_y were injected by generate_in_cells
        # TODO: This is hacky, I want plugins to operate without needing to know anything about generate_in_cells
        root_x = cfg.center_x if cfg.center_x is not None else cfg.root_x
        root_y = cfg.center_y if cfg.center_y is not None else cfg.root_y

        logger.info(
            f"Generating venation pattern from root ({root_x}, {root_y}) "
            f"with {cfg.num_leaves} attractors.")

        np.random.seed(cfg.seed)

        # 1. Distribute random attractors (leaves)
        xs = np.random.uniform(minx, maxx, cfg.num_leaves)
        ys = np.random.uniform(miny, maxy, cfg.num_leaves)

        # Keep only the leaves that strictly fall inside the complex boundary
        valid_leaves = []
        for lx, ly in zip(xs, ys):
            if boundary.contains(Point(lx, ly)):
                valid_leaves.append([lx, ly])
        leaves = np.array(valid_leaves)

        if len(leaves) == 0:
            logger.warning("No attractors generated within boundary.")
            return state

        # 2. Initialize the network with a single root node
        

        nodes = np.array([[root_x, root_y]])
        raw_lines = []

        # 3. Grow the network
        iterations = 0
        for iterations in range(cfg.max_iterations):
            if len(leaves) == 0:
                break

            # Build spatial index for fast nearest-neighbor lookups
            node_tree = cKDTree(nodes)
            distances, indices = node_tree.query(
                leaves, distance_upper_bound=cfg.attract_distance)

            active_nodes = {
            }  # node_index -> list of normalized direction vectors
            leaves_to_remove = []

            for i, (dist, node_idx) in enumerate(zip(distances, indices)):
                if dist < cfg.kill_distance:
                    leaves_to_remove.append(i)
                elif dist < cfg.attract_distance and node_idx != len(nodes):
                    # Calculate vector from node to leaf
                    leaf = leaves[i]
                    node = nodes[node_idx]
                    direction = leaf - node
                    norm = np.linalg.norm(direction)
                    if norm > 0:
                        direction = direction / norm
                        if node_idx not in active_nodes:
                            active_nodes[node_idx] = []
                        active_nodes[node_idx].append(direction)

            # Halt if the network has stalled
            if not active_nodes and not leaves_to_remove:
                break

            # Remove consumed leaves
            if leaves_to_remove:
                leaves = np.delete(leaves, leaves_to_remove, axis=0)

            # Grow active nodes toward the average direction of their attractors
            new_nodes = []
            for node_idx, vectors in active_nodes.items():
                avg_dir = np.mean(vectors, axis=0)
                norm = np.linalg.norm(avg_dir)
                if norm > 0:
                    avg_dir = avg_dir / norm
                    new_pos = nodes[node_idx] + avg_dir * cfg.segment_length
                    new_nodes.append(new_pos)
                    raw_lines.append(LineString([nodes[node_idx], new_pos]))

            if new_nodes:
                nodes = np.vstack((nodes, new_nodes))

        # --- THE FIX: MERGE THE INTERLEAVED SEGMENTS ---
        # linemerge joins contiguous segments into long paths, breaking only at branching junctions
        merged_geometry = linemerge(raw_lines)

        merged_lines = []
        if isinstance(merged_geometry, LineString):
            merged_lines = [merged_geometry]
        elif isinstance(merged_geometry, MultiLineString):
            merged_lines = list(merged_geometry.geoms)
        else:
            merged_lines = raw_lines  # Safe fallback if something bizarre happens

        logger.info(
            f"Growth complete. Merged {len(raw_lines)} micro-segments into {len(merged_lines)} contiguous branches."
        )

        # 4. Clip final merged paths to boundary
        clipped_lines: List[LineString] = []
        for line in merged_lines:
            if line.intersects(boundary):
                clipped = line.intersection(boundary)
                if isinstance(clipped, LineString) and not clipped.is_empty:
                    clipped_lines.append(clipped)
                elif isinstance(clipped, MultiLineString):
                    for sub_line in clipped.geoms:
                        if not sub_line.is_empty:
                            clipped_lines.append(sub_line)

        logger.success(
            f"Venation complete. Yielded {len(clipped_lines)} final toolpaths.")

        return PipelineState(boundary=state.boundary,
                             lines=state.lines + clipped_lines,
                             operation_name="venation")
