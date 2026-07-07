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

    def get_final_lines(self):
        return self.history[-1].lines
