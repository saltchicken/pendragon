from typing import Protocol

from loguru import logger

from .models import PipelineState


class StateStore(Protocol):
    """Defines the contract for caching pipeline history."""

    def get(self, index: int) -> PipelineState:
        """Retrieve a specific state snapshot by its index."""
        ...

    def get_last(self) -> PipelineState:
        """Retrieve the most recently computed state."""
        ...

    def append(self, state: PipelineState) -> None:
        """Cache a newly computed state."""
        ...

    def truncate(self, valid_length: int) -> None:
        """Drop all cached states from 'valid_length' onwards."""
        ...

    def reset(self, initial_state: PipelineState) -> None:
        """Clear the store and set a new base state."""
        ...

    def __len__(self) -> int:
        """Return the number of cached states."""
        ...


class InMemoryStateStore:
    """The default list-based cache, identical to the original engine behavior."""

    def __init__(self, initial_state: PipelineState):
        self._history: list[PipelineState] = [initial_state]

    def get(self, index: int) -> PipelineState:
        return self._history[index]

    def get_last(self) -> PipelineState:
        return self._history[-1]

    def append(self, state: PipelineState) -> None:
        self._history.append(state)

    def truncate(self, valid_length: int) -> None:
        if len(self._history) > valid_length:
            logger.debug(f"Truncating state history to length {valid_length}.")
            self._history = self._history[:valid_length]

    def reset(self, initial_state: PipelineState) -> None:
        self._history = [initial_state]

    def __len__(self) -> int:
        return len(self._history)
