import math
from typing import List, Literal, Optional, Tuple

from loguru import logger
from pydantic import BaseModel
from pydantic import Field
from shapely.affinity import affine_transform
from shapely.geometry import LineString

from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation


class IFSTransform(BaseModel):
    """Configuration for a single branch of the fractal."""
    matrix: list[float] = Field(
        ..., 
        min_length=6, 
        max_length=6,
        description="Affine matrix: [a, b, d, e, xoff, yoff]"
    )
    variation: Literal["linear", "sinusoidal", "spherical", "swirl"] = Field(
        default="linear",
        description="The non-linear math function applied after the affine transform."
    )


class IFSConfig(BaseModel):
    iterations: int = Field(default=3, ge=1, le=8)
    transforms: list[IFSTransform] = Field(default_factory=list)


@register_operation("ifs", config_class=IFSConfig)
class IFSMod(PipelineOperation):

    def apply_variation(self, x: float, y: float, var_type: str) -> Tuple[float, float]:
        """
        Applies non-linear math to the coordinates. 
        Note: Because CNC coordinates are typically large (e.g., 0-200mm), 
        we apply scaling factors so the math behaves beautifully.
        """
        if var_type == "linear":
            return x, y
            
        elif var_type == "sinusoidal":
            # Creates rippling, wave-like interference patterns
            scale = 20.0
            return (math.sin(x / scale) * scale * 2, 
                    math.sin(y / scale) * scale * 2)
                    
        elif var_type == "spherical":
            # Inverts the geometry inside-out like a glass marble
            # Shift slightly to prevent division by zero
            r2 = (x**2 + y**2) + 1e-6 
            radius = 10000.0  # Controls the "size" of the glass sphere
            return ((x / r2) * radius, (y / r2) * radius)
            
        elif var_type == "swirl":
            # Twists the coordinates based on their distance from origin
            r2 = (x**2 + y**2) / 5000.0
            sin_r2 = math.sin(r2)
            cos_r2 = math.cos(r2)
            return (x * sin_r2 - y * cos_r2, x * cos_r2 + y * sin_r2)
            
        return x, y

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        cfg = self.config or IFSConfig()
        ctx = context or PipelineContext()
        
        current_lines = state.lines
        if not current_lines:
            return state

        iterations = ctx.variables.get("iterations", cfg.iterations)
        
        logger.info(f"Applying Advanced IFS ({len(cfg.transforms)} transforms, {iterations} iterations)...")
        
        working_lines = current_lines
        
        for i in range(iterations):
            next_lines: list[LineString] = []
            
            for transform_cfg in cfg.transforms:
                matrix = transform_cfg.matrix
                variation = transform_cfg.variation
                
                for line in working_lines:
                    if line.is_empty:
                        continue
                        
                    # 1. Apply the standard Affine Transform (scale/rotate/translate)
                    affine_line = affine_transform(line, matrix)
                    
                    # 2. Apply the Non-Linear Variation
                    if variation != "linear":
                        warped_coords = [
                            self.apply_variation(x, y, variation) 
                            for x, y in affine_line.coords
                        ]
                        next_lines.append(LineString(warped_coords))
                    else:
                        next_lines.append(affine_line)
                    
            working_lines = next_lines
            logger.debug(f"IFS Iteration {i+1} complete: {len(working_lines)} paths.")
            
        logger.success(f"IFS generation complete. Yielded {len(working_lines)} lines.")
        return PipelineState(
            boundary=state.boundary,
            lines=working_lines,
            operation_name="ifs"
        )

    def build_custom_ui(self, window, op_index):
        """
        Builds a custom GUI for the IFS plugin. 
        PyQt5 is imported locally to ensure headless CLI compatibility.
        """
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QComboBox
        from PyQt5.QtWidgets import QDoubleSpinBox
        from PyQt5.QtWidgets import QFrame
        from PyQt5.QtWidgets import QGridLayout
        from PyQt5.QtWidgets import QGroupBox
        from PyQt5.QtWidgets import QHBoxLayout
        from PyQt5.QtWidgets import QLabel
        from PyQt5.QtWidgets import QPushButton
        from PyQt5.QtWidgets import QSpinBox
        from PyQt5.QtWidgets import QVBoxLayout
        from PyQt5.QtWidgets import QWidget

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Helper Callbacks to sync with the main window ---
        def trigger_recalc():
            if window._pending_op_index is None:
                window._pending_op_index = op_index
            else:
                window._pending_op_index = min(window._pending_op_index, op_index)
            window.debounce_timer.start()

        def add_transform():
            self.config.transforms.append(IFSTransform(matrix=[1.0, 0.0, 0.0, 1.0, 0.0, 0.0], variation="linear"))
            window.build_ui_for_current_step()
            trigger_recalc()

        def remove_transform(idx):
            if 0 <= idx < len(self.config.transforms):
                self.config.transforms.pop(idx)
                window.build_ui_for_current_step()
                trigger_recalc()

        # --- 1. Iterations Spinner ---
        iter_layout = QHBoxLayout()
        iter_layout.addWidget(QLabel("Iterations:"))
        iter_spin = QSpinBox()
        iter_spin.setRange(1, 8)
        iter_spin.setValue(self.config.iterations)
        def update_iter(val):
            self.config.iterations = val
            trigger_recalc()
        iter_spin.valueChanged.connect(update_iter)
        iter_layout.addWidget(iter_spin)
        layout.addLayout(iter_layout)

        # --- 2. Transforms List ---
        list_group = QGroupBox("Fractal Branches (IFS Transforms)")
        list_group.setStyleSheet("QGroupBox { border: 1px solid #444; border-radius: 4px; padding-top: 15px; }")
        list_layout = QVBoxLayout(list_group)
        list_layout.setSpacing(10)

        for item_idx, transform in enumerate(self.config.transforms):
            frame = QFrame()
            frame.setStyleSheet("QFrame { background-color: #252526; border: 1px solid #333; border-radius: 4px; }")
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(8, 8, 8, 8)

            header_layout = QHBoxLayout()
            header_layout.addWidget(QLabel(f"<b>Branch {item_idx + 1}</b>"))
            btn_remove = QPushButton("Remove")
            btn_remove.setStyleSheet("background-color: #5a1c1c; border: none; padding: 4px; border-radius: 2px;")
            btn_remove.setFixedWidth(60)
            btn_remove.clicked.connect(lambda checked, i=item_idx: remove_transform(i))
            header_layout.addWidget(btn_remove, alignment=Qt.AlignRight)
            frame_layout.addLayout(header_layout)

            # Matrix 2x3 Grid
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            labels = ["a (scale X)", "b (shear Y)", "d (shear X)", "e (scale Y)", "X Offset", "Y Offset"]
            
            for i in range(6):
                spin = QDoubleSpinBox()
                spin.setRange(-1000.0, 1000.0)
                spin.setDecimals(3)
                spin.setSingleStep(0.1)
                spin.setValue(transform.matrix[i])
                spin.setKeyboardTracking(False)
                
                # Capture i and transform instance safely for the callback
                def update_matrix(val, mat_idx=i, t=transform):
                    t.matrix[mat_idx] = val
                    trigger_recalc()
                    
                spin.valueChanged.connect(update_matrix)
                
                row, col = divmod(i, 2)
                lbl = QLabel(labels[i])
                lbl.setStyleSheet("color: #888; font-size: 10px;")
                box_layout = QVBoxLayout()
                box_layout.addWidget(lbl)
                box_layout.addWidget(spin)
                box_layout.setSpacing(2)
                grid.addLayout(box_layout, row, col)

            frame_layout.addLayout(grid)

            # Variation Selector
            var_layout = QHBoxLayout()
            var_layout.addWidget(QLabel("Variation:"))
            combo = QComboBox()
            combo.addItems(["linear", "sinusoidal", "spherical", "swirl"])
            combo.setCurrentText(transform.variation)
            
            def update_variation(text, t=transform):
                t.variation = text
                trigger_recalc()
                
            combo.currentTextChanged.connect(update_variation)
            var_layout.addWidget(combo)
            frame_layout.addLayout(var_layout)

            list_layout.addWidget(frame)

        btn_add = QPushButton("+ Add Transform Branch")
        btn_add.setStyleSheet("background-color: #2a2d32; color: #4CAF50; font-weight: bold; border: 1px dashed #555;")
        btn_add.clicked.connect(add_transform)
        list_layout.addWidget(btn_add)

        layout.addWidget(list_group)
        return container
