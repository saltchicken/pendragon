import math
from typing import Optional

from loguru import logger
from pydantic import Field
from shapely.geometry import Polygon

from pendragon.engine import PipelineContext
from pendragon.engine import PipelineOperation
from pendragon.engine import PipelineState
from pendragon.engine import register_operation
from pendragon.engine.registry import BasePluginConfig
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
    tier_1_op: str = Field(default="spiral")
    tier_1_settings: dict = Field(default_factory=dict)
    
    # Tier 2 (Mid-Dark)
    tier_2_op: str = Field(default="concentric")
    tier_2_settings: dict = Field(default_factory=dict)
    
    # Tier 3 (Mid-Light)
    tier_3_op: str = Field(default="grid_lines")
    tier_3_settings: dict = Field(default_factory=dict)
    
    # Tier 4 (Lightest)
    tier_4_op: str = Field(default="")
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
        
        # TODO: This needs to be fixed with new registry
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
        """
        Builds a custom GUI for the Image Multi-Tier plugin. 
        PyQt5 is imported locally to ensure headless CLI compatibility.
        """
        from PyQt5.QtWidgets import QComboBox
        from PyQt5.QtWidgets import QDoubleSpinBox
        from PyQt5.QtWidgets import QFileDialog
        from PyQt5.QtWidgets import QFormLayout
        from PyQt5.QtWidgets import QGroupBox
        from PyQt5.QtWidgets import QHBoxLayout
        from PyQt5.QtWidgets import QLabel
        from PyQt5.QtWidgets import QLineEdit
        from PyQt5.QtWidgets import QPushButton
        from PyQt5.QtWidgets import QVBoxLayout
        from PyQt5.QtWidgets import QWidget

        from pendragon.engine.registry import OPERATION_REGISTRY
        from pendragon.gui.widgets import WidgetFactory

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

        # --- 1. Source Image Selection ---
        img_layout = QHBoxLayout()
        img_layout.addWidget(QLabel("Source Image:"))
        img_line = QLineEdit(self.config.source_image)
        
        def update_img(text):
            self.config.source_image = text
            trigger_recalc()
            
        img_line.textChanged.connect(update_img)
        img_layout.addWidget(img_line)

        btn_browse = QPushButton("Browse...")
        def browse_file():
            path, _ = QFileDialog.getOpenFileName(window, "Select Image", "", "Images (*.png *.jpg *.jpeg);;All Files (*)")
            if path:
                img_line.setText(path)
                
        btn_browse.clicked.connect(browse_file)
        img_layout.addWidget(btn_browse)
        layout.addLayout(img_layout)

        # --- 2. Global Cell Size ---
        cs_layout = QHBoxLayout()
        cs_layout.addWidget(QLabel("Grid Cell Size:"))
        cs_spin = QDoubleSpinBox()
        cs_spin.setRange(0.1, 1000.0)
        cs_spin.setSingleStep(0.5)
        cs_spin.setValue(self.config.cell_size)
        
        def update_cs(val):
            self.config.cell_size = val
            trigger_recalc()
            
        cs_spin.valueChanged.connect(update_cs)
        cs_layout.addWidget(cs_spin)
        layout.addLayout(cs_layout)

        # --- 3. Dynamic Tier Layouts ---
        tier_names = [
            "Tier 1 (Darkest: 75%-100%)", 
            "Tier 2 (Mid-Dark: 50%-75%)",
            "Tier 3 (Mid-Light: 25%-50%)", 
            "Tier 4 (Lightest: 0%-25%)"
        ]

        # Standardize the available operations mapping
        available_ops = ["None"] + sorted(OPERATION_REGISTRY.keys())

        for i in range(1, 5):
            op_attr = f"tier_{i}_op"
            settings_attr = f"tier_{i}_settings"

            group = QGroupBox(tier_names[i-1])
            group.setStyleSheet("QGroupBox { border: 1px solid #444; border-radius: 4px; padding-top: 15px; margin-top: 10px; }")
            group_layout = QFormLayout(group)

            combo = QComboBox()
            combo.addItems(available_ops)

            current_op = getattr(self.config, op_attr)
            if current_op in available_ops:
                combo.setCurrentText(current_op)
            else:
                combo.setCurrentText("None")

            # Callback factory to trap the correct tier variables
            def make_combo_cb(op_key, set_key):
                def on_change(text):
                    new_val = "" if text == "None" else text
                    setattr(self.config, op_key, new_val)
                    setattr(self.config, set_key, {})  # Clear out old settings
                    window.build_ui_for_current_step() # Redraw the whole UI panel
                    trigger_recalc()
                return on_change

            combo.currentTextChanged.connect(make_combo_cb(op_attr, settings_attr))
            group_layout.addRow("Generator:", combo)

            # Delegate standard setting fields back to Pendragon's WidgetFactory
            if current_op and current_op in OPERATION_REGISTRY:
                ConfigClass = OPERATION_REGISTRY[current_op]["config"]
                current_settings = getattr(self.config, settings_attr)

                if ConfigClass:
                    for field_name, field_info in ConfigClass.model_fields.items():
                        # Extract the existing value or fall back to the plugin's default
                        val = current_settings.get(field_name, field_info.default if field_info.default is not None else 0.0)

                        def make_setting_cb(t_idx, f_name):
                            def cb(new_val):
                                target_dict = getattr(self.config, f"tier_{t_idx}_settings")
                                target_dict[f_name] = new_val
                                trigger_recalc()
                            return cb

                        widget_container = WidgetFactory.build_field_widget(
                            field_name, field_info, val, make_setting_cb(i, field_name), parent=window
                        )
                        if widget_container:
                            group_layout.addRow(f"↳ {field_name}", widget_container)

            layout.addWidget(group)

        return container
