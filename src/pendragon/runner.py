from typing import List

from loguru import logger

from pendragon.core import PipelineOperation
from pendragon.core import PipelineState


class PipelineRunner:

    def __init__(self, initial_state: PipelineState):
        # The history stack always starts with the raw, unmodified state
        self.history: List[PipelineState] = [initial_state]
        self.operations: List[PipelineOperation] = []

    def add_operation(self, operation: PipelineOperation):
        self.operations.append(operation)

    def execute_all(self):
        """Runs the entire pipeline from the beginning."""
        # Reset history to just the initial state to avoid duplicating steps
        # if executed multiple times
        self.history = [self.history[0]]

        for i, op in enumerate(self.operations):
            current_state = self.history[-1]
            logger.info(f"Running operation {i}: {op.__class__.__name__}")

            # Generate the new state and push it to the history stack
            new_state = op.process(current_state)
            self.history.append(new_state)

    def get_state_at_step(self, step_index: int) -> PipelineState:
        """Allows you to move 'back and forth' by grabbing any historical state."""
        try:
            return self.history[step_index]
        except IndexError:
            logger.error(
                f"Step {step_index} does not exist. Returning latest state.")
            return self.history[-1]

    def recompute_from(self, step_index: int):
        """Re-runs the pipeline starting from a specific operation index."""
        if step_index < 0 or step_index >= len(self.operations):
            return

        # Truncate history to the state just before the modified step
        # history[0] is the initial boundary state
        self.history = self.history[:step_index + 1]

        # Re-run from the modified step to the end
        for i in range(step_index, len(self.operations)):
            op = self.operations[i]
            current_state = self.history[-1]
            logger.info(f"Recomputing operation {i}: {op.__class__.__name__}")
            
            new_state = op.process(current_state)
            self.history.append(new_state)

    def get_final_lines(self):
        return self.history[-1].lines
