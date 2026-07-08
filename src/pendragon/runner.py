import inspect
from typing import List
from loguru import logger
from pendragon.core import PipelineOperation, PipelineState

class PipelineRunner:
    def __init__(self, initial_state: PipelineState):
        self.history: List[PipelineState] = [initial_state]
        self.operations: List[PipelineOperation] = []

    def add_operation(self, operation: PipelineOperation):
        self.operations.append(operation)

    # TODO: I shouldn't need _safe_process. Should implement callbakcs for all plugins
    def _safe_process(self, op: PipelineOperation, state: PipelineState, cancel_callback=None, progress_callback=None):
        """Intelligently passes callbacks only if the plugin's signature supports them."""
        sig = inspect.signature(op.process)
        kwargs = {}
        
        # Check for explicit parameters or **kwargs support
        supports_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        
        if 'cancel_callback' in sig.parameters or supports_kwargs:
            kwargs['cancel_callback'] = cancel_callback
        if 'progress_callback' in sig.parameters or supports_kwargs:
            kwargs['progress_callback'] = progress_callback
            
        return op.process(state, **kwargs)

    def execute_all(self, cancel_callback=None, progress_callback=None):
        self.history = [self.history[0]]
        total_ops = len(self.operations)
        
        for i, op in enumerate(self.operations):
            if cancel_callback: 
                cancel_callback()
            if progress_callback:
                progress_callback(int((i / max(1, total_ops)) * 100), f"Running {op.__class__.__name__}...")
                
            current_state = self.history[-1]
            logger.info(f"Running operation {i}: {op.__class__.__name__}")
            
            new_state = self._safe_process(op, current_state, cancel_callback, progress_callback)
            self.history.append(new_state)

    def get_state_at_step(self, step_index: int) -> PipelineState:
        try:
            return self.history[step_index]
        except IndexError:
            logger.error(f"Step {step_index} does not exist. Returning latest state.")
            return self.history[-1]

    def recompute_from(self, step_index: int, target_step: int = None, cancel_callback=None, progress_callback=None):
        """Re-runs the pipeline starting from a specific operation index up to an optional target step."""
        if step_index < 0 or step_index >= len(self.operations):
            return

        if target_step is None:
            target_step = len(self.operations)
        
        target_step = min(target_step, len(self.operations))
        self.history = self.history[:step_index + 1]

        total_steps = target_step - step_index

        for i in range(step_index, target_step):
            if cancel_callback:
                cancel_callback()
                
            op = self.operations[i]
            if progress_callback:
                progress_percent = int(((i - step_index) / max(1, total_steps)) * 100)
                progress_callback(progress_percent, f"Computing {op.__class__.__name__}...")
                
            current_state = self.history[-1]
            new_state = self._safe_process(op, current_state, cancel_callback, progress_callback)
            self.history.append(new_state)
            
        if progress_callback:
            progress_callback(100, "Complete")

    def get_final_lines(self):
        return self.history[-1].lines
