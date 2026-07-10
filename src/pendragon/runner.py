import inspect
from typing import List, Optional

from loguru import logger

from pendragon.core import PipelineOperation
from pendragon.core import PipelineState
from pendragon.core.models import PipelineContext


class PipelineRunner:

    def __init__(self, initial_state: PipelineState):
        self.history: List[PipelineState] = [initial_state]
        self.operations: List[PipelineOperation] = []

    def add_operation(self, operation: PipelineOperation):
        self.operations.append(operation)

    def execute_all(self):
        self.history = [self.history[0]]
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

    def get_state_at_step(self, step_index: int) -> PipelineState:
        try:
            return self.history[step_index]
        except IndexError:
            logger.error(
                f"Step {step_index} does not exist. Returning latest state.")
            return self.history[-1]

    def recompute_from(self,
                       step_index: int,
                       target_step: Optional[int] = None):
        """Re-runs the pipeline starting from a specific operation index up to an optional target step."""
        if step_index < 0 or step_index >= len(self.operations):
            return

        if target_step is None:
            target_step = len(self.operations)

        # Ensure we don't try to compute past the end of the pipeline
        target_step = min(target_step, len(self.operations))

        # Truncate history to the state just before the modified step
        self.history = self.history[:step_index + 1]

        empty_context = PipelineContext()

        # Re-run from the modified step to the target_step
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

    def get_final_lines(self):
        return self.history[-1].lines
