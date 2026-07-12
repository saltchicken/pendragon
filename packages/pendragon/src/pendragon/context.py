from typing import Optional
from nodeweaver.models import PipelineContext

class PendragonContext:
    """Wrapper to provide Pendragon-specific attributes while keeping nodeweaver clean."""
    
    def __init__(self, base_context: PipelineContext):
        self._base = base_context
        # Access these from the 'variables' dict in the base context
        self.local_center_x = base_context.get("local_center_x")
        self.local_center_y = base_context.get("local_center_y")
        self.local_rotation = base_context.get("local_rotation")

    def get(self, key, default=None):
        return self._base.get(key, default)
