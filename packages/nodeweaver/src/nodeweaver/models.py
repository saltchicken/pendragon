from dataclasses import dataclass, field
from typing import Any, Dict, TypeVar

# A generic type representing the state of any downstream domain
T_State = TypeVar("T_State")

@dataclass
class PipelineContext:
    """Out-of-band execution metadata and global variables passed down the pipeline."""
    variables: Dict[str, Any] = field(default_factory=dict)
    current_step: int = 0
    total_steps: int = 0

    def get(self, key: str, default: Any = None) -> Any:
        """Safely fetch variables from the context."""
        return self.variables.get(key, default)
