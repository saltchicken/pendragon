from typing import Dict, Optional
import math

from loguru import logger
from pydantic import Field
from shapely.geometry import Polygon

from pendragon.engine import PipelineContext, PipelineOperation, PipelineState, register_operation
from pendragon.engine.registry import OPERATION_REGISTRY, BasePluginConfig
from pendragon.utils import ImageSampler


class ImageMultiTierConfig(BasePluginConfig):
    source_image: str = Field(
        default="", 
        description="Path to the source image.", 
        json_schema_extra={"widget": "file_picker"}
    )
    cell_size: float = Field(
        default=5.0, 
        description="Size of the grid cells."
    )
    
    # Tier 1 (Darkest)
    tier_1_op: str = Field(default="spiral", json_schema_extra={"widget": "operation_selector"})
    tier_1_settings: dict = Field(default_factory=dict)
    
    # Tier 2 (Mid-Dark)
    tier_2_op: str = Field(default="concentric", json_schema_extra={"widget": "operation_selector"})
    tier_2_settings: dict = Field(default_factory=dict)
    
    # Tier 3 (Mid-Light)
    tier_3_op: str = Field(default="grid_lines", json_schema_extra={"widget": "operation_selector"})
    tier_3_settings: dict = Field(default_factory=dict)
    
    # Tier 4 (Lightest)
    tier_4_op: str = Field(default="", json_schema_extra={"widget": "operation_selector"})
    tier_4_settings: dict = Field(default_factory=dict)


@register_operation("image_multi_tier", config_class=ImageMultiTierConfig)
class ImageMultiTierGen(PipelineOperation):
    """
    Samples an image across a grid and assigns one of 4 operations 
    to each cell based on the darkness threshold (0.0 to 1.0).
    """

    def _load_generator(self, op_name: str, settings: dict):
        if not op_name or op_name.lower() == "none":
            return None
        
        op_info = OPERATION_REGISTRY.get(op_name)
        if not op_info:
            logger.warning(f"Operation '{op_name}' not found in registry.")
            return None
            
        PluginClass = op_info["class"]
        ConfigClass = op_info["config"]
        
        config = ConfigClass(**settings) if ConfigClass else None
        return PluginClass(config=config)

    def process(self,
                state: PipelineState,
                context: Optional[PipelineContext] = None) -> PipelineState:
        
        cfg = self.config or ImageMultiTierConfig()
        
        if not cfg.source_image:
            logger.warning("No source image provided for image_multi_tier.")
            return state

        effective_boundary = self.get_effective_boundary(state)
        minx, miny, maxx, maxy = effective_boundary.bounds

        logger.info(f"Loading Multi-Tier image: {cfg.source_image}")
        sampler = ImageSampler(cfg.source_image, effective_boundary.bounds)
        
        # Pre-instantiate the generators to avoid rebuilding them thousands of times
        tier_1_gen = self._load_generator(cfg.tier_1_op, cfg.tier_1_settings) # 0.75 - 1.0
        tier_2_gen = self._load_generator(cfg.tier_2_op, cfg.tier_2_settings) # 0.50 - 0.75
        tier_3_gen = self._load_generator(cfg.tier_3_op, cfg.tier_3_settings) # 0.25 - 0.50
        tier_4_gen = self._load_generator(cfg.tier_4_op, cfg.tier_4_settings) # 0.00 - 0.25

        new_lines = []
        cell_size = cfg.cell_size
        
        cols = math.ceil((maxx - minx) / cell_size)
        rows = math.ceil((maxy - miny) / cell_size)

        logger.info(f"Processing {cols}x{rows} grid cells...")

        for col in range(cols):
            for row in range(rows):
                x = minx + (col * cell_size)
                y = miny + (row * cell_size)
                cx, cy = x + (cell_size / 2), y + (cell_size / 2)
                
                # Check if cell center is inside the main boundary
                import shapely.geometry
                if not effective_boundary.contains(shapely.geometry.Point(cx, cy)):
                    continue

                # Sample the image (returns 0.0 for white, 1.0 for black)
                darkness = sampler.get_darkness(cx, cy)
                
                # Determine which generator to use based on the quartile
                active_gen = None
                if darkness >= 0.75:
                    active_gen = tier_1_gen
                elif darkness >= 0.50:
                    active_gen = tier_2_gen
                elif darkness >= 0.25:
                    active_gen = tier_3_gen
                else:
                    active_gen = tier_4_gen
                
                if active_gen:
                    # Create the local bounding box for this cell
                    cell_poly = Polygon([
                        (x, y), (x + cell_size, y), 
                        (x + cell_size, y + cell_size), (x, y + cell_size), 
                        (x, y)
                    ])
                    
                    # Create isolated state and context for the sub-generator
                    sub_state = PipelineState(boundary=cell_poly)
                    sub_ctx = PipelineContext(local_center_x=cx, local_center_y=cy)
                    
                    try:
                        result_state = active_gen.process(sub_state, sub_ctx)
                        new_lines.extend(result_state.lines)
                    except Exception as e:
                        logger.error(f"Error running {active_gen.__class__.__name__} at cell ({x},{y}): {e}")

        logger.success(f"Multi-tier image processing generated {len(new_lines)} segments.")
        return PipelineState(boundary=state.boundary,
                             lines=state.lines + new_lines,
                             operation_name="image_multi_tier")

    def build_custom_ui(self, window, op_index):
        """Builds a dynamic custom GUI to handle nested tier configurations."""
        from PyQt5.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
            QDoubleSpinBox, QComboBox, QGroupBox, QLineEdit, QFileDialog, QFormLayout
        )
        from pendragon.gui.widgets import WidgetFactory

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # Triggers the pipeline recalculation timer
        def trigger_recalc():
            if window._pending_op_index is None:
                window._pending_op_index = op_index
            else:
                window._pending_op_index = min(window._pending_op_index, op_index)
            window.debounce_timer.start()

        # --- 1. Base Image & Grid Settings ---
        base_group = QGroupBox("Base Settings")
        base_group.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #444; border-radius: 4px; padding-top: 15px; }")
        base_layout = QFormLayout(base_group)
        
        img_layout = QHBoxLayout()
        img_edit = QLineEdit(self.config.source_image)
        img_btn = QPushButton("Browse...")
        
        def update_img(text):
            self.config.source_image = text
            trigger_recalc()
            
        def browse_img():
            path, _ = QFileDialog.getOpenFileName(window, "Select Source Image", "", "Images (*.png *.jpg *.jpeg);;All Files (*)")
            if path:
                img_edit.setText(path)
                
        img_edit.textChanged.connect(update_img)
        img_btn.clicked.connect(browse_img)
        img_layout.addWidget(img_edit)
        img_layout.addWidget(img_btn)
        base_layout.addRow("Source Image:", img_layout)

        cell_spin = QDoubleSpinBox()
        cell_spin.setRange(0.1, 1000.0)
        cell_spin.setSingleStep(0.5)
        cell_spin.setValue(self.config.cell_size)
        
        def update_cell_size(val):
            self.config.cell_size = val
            trigger_recalc()
            
        cell_spin.valueChanged.connect(update_cell_size)
        base_layout.addRow("Cell Size:", cell_spin)
        
        layout.addWidget(base_group)

        # --- 2. Dynamic Tiers 1 through 4 ---
        tier_names = ["Tier 1 (Darkest, >75%)", "Tier 2 (Mid-Dark, >50%)", "Tier 3 (Mid-Light, >25%)", "Tier 4 (Lightest, <25%)"]
        op_keys = [""] + sorted(list(OPERATION_REGISTRY.keys()))

        for i in range(1, 5):
            tier_group = QGroupBox(tier_names[i-1])
            tier_group.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #444; border-radius: 4px; padding-top: 15px; margin-top: 5px; }")
            tier_layout = QVBoxLayout(tier_group)
            
            op_attr = f"tier_{i}_op"
            set_attr = f"tier_{i}_settings"
            
            # Sub-generator Combobox
            combo_layout = QHBoxLayout()
            combo_layout.addWidget(QLabel("Generator:"))
            combo = QComboBox()
            combo.addItems(op_keys)
            
            current_op = getattr(self.config, op_attr)
            if current_op in op_keys:
                combo.setCurrentText(current_op)
                
            def on_op_changed(text, op_a=op_attr, set_a=set_attr):
                setattr(self.config, op_a, text)
                setattr(self.config, set_a, {})  # Clear out old settings
                # Force the entire property panel to rebuild so the new config widgets appear
                window.build_ui_for_current_step()
                trigger_recalc()
                
            combo.currentTextChanged.connect(on_op_changed)
            combo_layout.addWidget(combo)
            tier_layout.addLayout(combo_layout)

            # Retrieve and build widgets for the selected operation's specific Pydantic Config
            if current_op and current_op in OPERATION_REGISTRY:
                op_info = OPERATION_REGISTRY[current_op]
                ConfigClass = op_info["config"]
                
                if ConfigClass:
                    settings_form = QFormLayout()
                    current_settings = getattr(self.config, set_attr)
                    
                    for field_name, field_info in ConfigClass.model_fields.items():
                        # Extract the existing value, or fallback to the model's default
                        default_val = field_info.default if field_info.default is not None else 0.0
                        val = current_settings.get(field_name, default_val)
                        current_settings[field_name] = val  # Ensure dict is populated for saving
                        
                        # Closure callback to handle UI edits
                        def update_nested(new_val, sa=set_attr, fn=field_name):
                            getattr(self.config, sa)[fn] = new_val
                            trigger_recalc()
                            
                        # Use Pendragon's native WidgetFactory for standard sliders/spinners
                        widget = WidgetFactory.build_field_widget(
                            field_name, field_info, val, update_nested, parent=window
                        )
                        if widget:
                            settings_form.addRow(f"↳ {field_name}", widget)
                    
                    if settings_form.rowCount() > 0:
                        tier_layout.addLayout(settings_form)

            layout.addWidget(tier_group)

        return container
