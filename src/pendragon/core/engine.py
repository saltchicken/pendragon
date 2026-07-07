# src/pendragon/core/engine.py

from typing import List, Optional
import numpy as np
from vispy import app, scene
from loguru import logger
from shapely.geometry import Polygon, LineString

from pendragon.core.models import PipelineState
from pendragon.core.runner import PipelineRunner
from pendragon.core.registry import OPERATION_REGISTRY
from pendragon.pen import PenTool, PenConfig


class PipelineViewer(scene.SceneCanvas):
    def __init__(self, history: List[PipelineState]):
        super().__init__(keys='interactive', size=(800, 800), show=True)
        self.unfreeze()
        self.history = history
        self.current_step = 0
        self.view = self.central_widget.add_view()
        self.view.camera = 'panzoom'
        self.view.camera.aspect = 1.0

        self.lines_visual = scene.visuals.Line(parent=self.view.scene, color='white')
        self.boundary_visual = scene.visuals.Line(parent=self.view.scene, color='red')
        self.freeze()

        self.update_view()
        if self.history and self.history[0].boundary:
            minx, miny, maxx, maxy = self.history[0].boundary.bounds
            self.view.camera.set_range(x=(minx, maxx), y=(miny, maxy))
        else:
            try:
                self.view.camera.set_range()
            except ValueError:
                pass

    def on_key_press(self, event):
        if event.key.name == 'Right':
            self.current_step = min(self.current_step + 1, len(self.history) - 1)
            self.update_view()
        elif event.key.name == 'Left':
            self.current_step = max(self.current_step - 1, 0)
            self.update_view()
        elif event.key.name == 'Escape':
            self.close()

    def update_view(self):
        state = self.history[self.current_step]
        self.title = f"Step {self.current_step + 1}/{len(self.history)}: {state.operation_name} ({len(state.lines)} lines)"

        if state.boundary:
            bx, by = state.boundary.exterior.xy
            self.boundary_visual.set_data(pos=np.column_stack((bx, by)))
            self.boundary_visual.visible = True
        else:
            self.boundary_visual.visible = False

        if state.lines:
            pos = []
            connect = []
            idx = 0
            for line in state.lines:
                coords = np.array(line.coords)
                pos.append(coords)
                n_pts = len(coords)
                for i in range(n_pts - 1):
                    connect.append([idx + i, idx + i + 1])
                idx += n_pts
            self.lines_visual.set_data(pos=np.vstack(pos), connect=np.array(connect))
            self.lines_visual.visible = True
        else:
            self.lines_visual.visible = False


class PendragonEngine:
    def __init__(self, recipe: list, boundary: Optional[Polygon] = None):
        """
        Initializes the engine with a recipe and an optional boundary.
        """
        self.recipe = recipe
        # Hardcoded for now, but prepped for Issue #1 (Dynamic Boundaries)
        self.boundary = boundary or Polygon([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)])
        
        initial_state = PipelineState(boundary=self.boundary, operation_name="base_geometry")
        self.runner = PipelineRunner(initial_state)

    def build_pipeline(self) -> bool:
        """
        Validates the recipe and queues up the configured plugin operations.
        Returns True if successful, False if validation fails.
        """
        for step in self.recipe:
            op_name = step.get("operation")
            if not op_name:
                logger.error(f"Invalid step configuration, missing 'operation' key: {step}")
                return False

            op_info = OPERATION_REGISTRY.get(op_name)
            if not op_info:
                logger.error(f"Operation '{op_name}' not found in registry.")
                return False

            PluginClass = op_info["class"]
            ConfigClass = op_info["config"]
            
            validated_config = None
            if ConfigClass:
                try:
                    validated_config = ConfigClass(**step.get("settings", {}))
                    logger.success(f"Successfully validated config for {op_name}")
                except Exception as e:
                    logger.error(f"Configuration error for '{op_name}': {e}")
                    return False
                    
            plugin_instance = PluginClass(config=validated_config)
            self.runner.add_operation(plugin_instance)
            
        return True

    def run(self) -> List[LineString]:
        """
        Executes the pipeline sequentially and returns the final geometries.
        """
        self.runner.execute_all()
        return self.runner.get_final_lines()

    def export_gcode(self, lines: List[LineString], output_path: str, pen_config: Optional[PenConfig] = None):
        """
        Translates LineStrings into G-code using the PenTool context manager.
        """
        if not lines:
            logger.warning("No lines to export!")
            return
            
        config = pen_config or PenConfig()
        logger.info(f"Generating G-code to {output_path}...")
        
        with PenTool(config=config, output_filename=output_path) as pen:
            for line in lines:
                points = list(line.coords)
                pen.draw_path(points)

    def visualize(self):
        """
        Renders the pipeline history in an interactive Vispy window.
        """
        history = self.runner.history
        if not history:
            logger.warning("No pipeline history to visualize!")
            return
            
        logger.info("Opening visualization window. Use Left/Right arrows to step through operations.")
        
        canvas = PipelineViewer(history)
        app.run()
