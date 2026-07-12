import inspect
from typing import Optional
from loguru import logger

from .models import PipelineContext, PipelineState
from .registry import PipelineOperation

class PipelineRunner:
    """Core headless runner. Memory-efficient, executes linearly, no history tracking."""

    def __init__(self, initial_state: PipelineState):
        self.initial_state = initial_state
        self.operations: list[PipelineOperation] = []
        self._final_state: Optional[PipelineState] = None

    def add_operation(self, operation: PipelineOperation):
        self.operations.append(operation)

    def execute_all(self):
        current_state = self.initial_state
        empty_context = PipelineContext()

        for i, op in enumerate(self.operations):
            logger.info(f"Running operation {i}: {op.__class__.__name__}")

            sig = inspect.signature(op.process)
            if 'context' in sig.parameters:
                current_state = op.process(current_state, context=empty_context)
            else:
                current_state = op.process(current_state)

        self._final_state = current_state

    def get_final_lines(self):
        if not self._final_state:
            return self.initial_state.lines
        return self._final_state.lines


class InteractiveRunner(PipelineRunner):
    """GUI-oriented runner. Tracks pipeline history and allows partial recomputation."""

    def __init__(self, initial_state: PipelineState):
        super().__init__(initial_state)
        self.history: list[PipelineState] = [initial_state]

    def execute_all(self):
        self.history = [self.initial_state]
        empty_context = PipelineContext()

        for i, op in enumerate(self.operations):
            current_state = self.history[-1]
            logger.info(f"Running operation {i}: {op.__class__.__name__}")

            sig = inspect.signature(op.process)
            if 'context' in sig.parameters:
                new_state = op.process(current_state, context=empty_context)
            else:
                new_state = op.process(current_state)

            self.history.append(new_state)

        self._final_state = self.history[-1]

    def get_state_at_step(self, step_index: int) -> PipelineState:
        try:
            return self.history[step_index]
        except IndexError:
            logger.error(f"Step {step_index} does not exist. Returning latest state.")
            return self.history[-1]

    def recompute_from(self, step_index: int, target_step: Optional[int] = None):
        """Re-runs the pipeline starting from a specific operation index."""
        if step_index < 0 or step_index >= len(self.operations):
            return

        if target_step is None:
            target_step = len(self.operations)

        target_step = min(target_step, len(self.operations))
        self.history = self.history[:step_index + 1]
        empty_context = PipelineContext()

        for i in range(step_index, target_step):
            op = self.operations[i]
            current_state = self.history[-1]
            logger.info(f"Recomputing operation {i}: {op.__class__.__name__}")

            sig = inspect.signature(op.process)
            if 'context' in sig.parameters:
                new_state = op.process(current_state, context=empty_context)
            else:
                new_state = op.process(current_state)

            self.history.append(new_state)

        self._final_state = self.history[-1]

    def get_final_lines(self):
        return self.history[-1].lines
