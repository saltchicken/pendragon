import numpy as np
from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon
from vispy import scene


class PipelineViewer(scene.SceneCanvas):

    def __init__(self, engine):
        super().__init__(keys='interactive',
                         size=(800, 800),
                         title="Pendragon Pipeline Visualizer",
                         show=True)
        self.unfreeze()
        self.engine = engine
        self.current_step = min(1, len(self.engine.runner.operations))
        self.show_vertices = False
        self.show_final_view = False

        self.on_step_changed = None
        self.on_close_requested = None
        self.on_stats_updated = None

        self.view = self.central_widget.add_view()
        self.view.camera = 'panzoom'
        self.view.camera.aspect = 1.0

        dummy_pos = np.zeros((2, 2), dtype=np.float32)

        self.lines_visual = scene.visuals.Line(pos=dummy_pos,
                                               parent=self.view.scene,
                                               color='white')
        self.boundary_visual = scene.visuals.Line(pos=dummy_pos,
                                                  parent=self.view.scene,
                                                  color='red')
        self.vertices_visual = scene.visuals.Markers(pos=dummy_pos,
                                                     parent=self.view.scene)

        self.lines_visual.visible = False
        self.boundary_visual.visible = False
        self.vertices_visual.visible = False

        self.freeze()
        self.update_view()

        history = self.engine.runner.history
        if history and history[0].boundary:
            minx, miny, maxx, maxy = history[0].boundary.bounds
            self.view.camera.set_range(x=(minx, maxx), y=(miny, maxy))
        else:
            try:
                self.view.camera.set_range()
            except ValueError:
                pass

    def step_forward(self):
        max_step = len(self.engine.runner.operations)
        if self.current_step < max_step:
            self.current_step += 1
            self.update_view()
            if self.on_step_changed is not None:
                self.on_step_changed()

    def step_backward(self):
        if self.current_step > 0:
            self.current_step -= 1
            self.update_view()
            if self.on_step_changed is not None:
                self.on_step_changed()

    def on_key_press(self, event):
        if event.key is None:
            return
        if event.key.name == 'Right':
            self.step_forward()
        elif event.key.name == 'Left':
            self.step_backward()
        elif event.key.name == 'Escape':
            if self.on_close_requested is not None:
                self.on_close_requested()
            else:
                self.close()

    def set_live_vectors(self, pos, connect):
        """Injects pre-computed numpy arrays directly into the GPU."""
        if len(pos) > 0:
            self.lines_visual.set_data(pos=pos, connect=connect)
            self.lines_visual.visible = True

            if self.show_vertices:
                self.vertices_visual.set_data(pos=pos,
                                              face_color='red',
                                              edge_color=None,
                                              size=10)
                self.vertices_visual.visible = True
            else:
                self.vertices_visual.visible = False
        else:
            self.lines_visual.visible = False
            self.vertices_visual.visible = False

    def set_live_lines(self, lines):
        """
        Used by local step-scrubbing. Converts Shapely objects on the fly,
        then routes them to the vectorized renderer.
        """
        if not lines:
            self.set_live_vectors(np.empty((0, 2)), np.empty((0, 2)))
            return

        coords_list = [
            np.array(line.coords, dtype=np.float32) for line in lines
        ]
        stacked_pos = np.vstack(coords_list)

        lengths = [len(c) for c in coords_list]
        connect_blocks = []
        current_idx = 0

        for n in lengths:
            if n > 1:
                starts = np.arange(current_idx,
                                   current_idx + n - 1,
                                   dtype=np.uint32)
                ends = starts + 1
                connect_blocks.append(np.column_stack((starts, ends)))
            current_idx += n

        final_connect = np.vstack(
            connect_blocks) if connect_blocks else np.empty(
                (0, 2), dtype=np.uint32)

        self.set_live_vectors(stacked_pos, final_connect)

    def update_view(self):
        target_step = len(self.engine.runner.operations
                         ) if self.show_final_view else self.current_step

        # Safely cap the display step to whatever history currently exists
        display_step = min(target_step, len(self.engine.runner.history) - 1)
        state = self.engine.runner.history[display_step]

        total_vertices = sum(len(line.coords) for line in state.lines)
        total_ops = len(self.engine.runner.operations)

        if self.on_stats_updated:
            self.on_stats_updated(self.current_step,
                                  total_ops, state.operation_name,
                                  len(state.lines), total_vertices,
                                  self.show_final_view)

        if state.boundary and not state.boundary.is_empty:
            polygons = []
            if isinstance(state.boundary, Polygon):
                polygons = [state.boundary]
            elif isinstance(state.boundary, MultiPolygon):
                polygons = list(state.boundary.geoms)

            # --- FAST VECTORIZED BOUNDARY PREP ---
            coords_list = []
            for poly in polygons:
                coords_list.append(np.array(poly.exterior.coords))
                for interior in poly.interiors:
                    coords_list.append(np.array(interior.coords))

            if coords_list:
                stacked_b_pos = np.vstack(coords_list)
                lengths = [len(c) for c in coords_list]
                connect_blocks = []
                current_idx = 0

                for n in lengths:
                    if n > 1:
                        # Rapidly generate [0,1], [1,2], [2,3] index pairs
                        starts = np.arange(current_idx, current_idx + n - 1)
                        ends = starts + 1
                        connect_blocks.append(np.column_stack((starts, ends)))
                    current_idx += n

                b_connect = np.vstack(
                    connect_blocks) if connect_blocks else np.empty((0, 2))

                self.boundary_visual.set_data(pos=stacked_b_pos,
                                              connect=b_connect)
                self.boundary_visual.visible = True
            else:
                self.boundary_visual.visible = False
        else:
            self.boundary_visual.visible = False

        self.set_live_lines(state.lines)
