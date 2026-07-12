import inspect
from typing import Generic, Optional
from loguru import logger

from .models import PipelineContext, T_State
from .registry import PipelineOperation

class PipelineRunner(Generic[T_State]):
    """Core headless runner. Memory-efficient, executes linearly, no history tracking."""

    def __init__(self, initial_state: T_State):
        self.initial_state = initial_state
        self.operations: list[PipelineOperation[T_State]] = []
        self._final_state: Optional[T_State] = None

    def add_operation(self, operation: PipelineOperation[T_State]):
        self.operations.append(operation)

    def execute_all(self):
        current_state = self.initial_state
        context = PipelineContext(total_steps=len(self.operations))

        for i, op in enumerate(self.operations):
            logger.info(f"Running operation {i}: {op.__class__.__name__}")
            context.current_step = i
            
            sig = inspect.signature(op.process)
            if 'context' in sig.parameters:
                current_state = op.process(current_state, context=context)
            else:
                current_state = op.process(current_state)

        self._final_state = current_state

    def get_final_state(self) -> T_State:
        return self._final_state or self.initial_state


class InteractiveRunner(PipelineRunner[T_State]):
    """GUI-oriented runner. Tracks pipeline history and allows partial recomputation."""

    def __init__(self, initial_state: T_State):
        super().__init__(initial_state)
        self.history: list[T_State] = [initial_state]

    def execute_all(self):
        self.history = [self.initial_state]
        context = PipelineContext(total_steps=len(self.operations))

        for i, op in enumerate(self.operations):
            current_state = self.history[-1]
            logger.info(f"Running operation {i}: {op.__class__.__name__}")
            context.current_step = i

            sig = inspect.signature(op.process)
            if 'context' in sig.parameters:
                new_state = op.process(current_state, context=context)
            else:
                new_state = op.process(current_state)

            self.history.append(new_state)

        self._final_state = self.history[-1]

    def get_state_at_step(self, step_index: int) -> T_State:
        try:
            return self.history[step_index]
        except IndexError:
            logger.error(f"Step {step_index} does not exist. Returning latest state.")
            return self.history[-1]

    def recompute_from(self, step_index: int, target_step: Optional[int] = None):
        if step_index < 0 or step_index >= len(self.operations):
            return

        if target_step is None:
            target_step = len(self.operations)

        target_step = min(target_step, len(self.operations))
        self.history = self.history[:step_index + 1]
        context = PipelineContext(total_steps=len(self.operations))

        for i in range(step_index, target_step):
            op = self.operations[i]
            current_state = self.history[-1]
            logger.info(f"Recomputing operation {i}: {op.__class__.__name__}")
            context.current_step = i

            sig = inspect.signature(op.process)
            if 'context' in sig.parameters:
                new_state = op.process(current_state, context=context)
            else:
                new_state = op.process(current_state)

            self.history.append(new_state)

        self._final_state = self.history[-1]
