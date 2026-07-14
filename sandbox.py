import sys

from shapely.geometry import Polygon

from pendragon.engine import load_plugins
from pendragon.engine import PendragonEngine


def main():
    load_plugins()
    boundary = Polygon([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)])

    recipe = [{
        "operation": "grid_lines",
        "settings": {
            "spacing": 20.0,
            "orientation": "crosshatch"
        }
    }, {
        "operation": "subdivide_lines",
        "settings": {
            "max_length": 5.0
        }
    }, {
        "operation": "simplify",
        "settings": {
            "tolerance": 0.5
        }
    }]

    print("Initializing Pendragon Engine...")
    engine = PendragonEngine(recipe=recipe, boundary=boundary)

    if not engine.build_pipeline():
        print("Failed to build pipeline. Check operation names and settings.")
        sys.exit(1)

    total_steps = engine.get_operation_count()
    print(f"Pipeline built successfully with {total_steps} operations.\n")
    print("--- Starting Interactive Stepper ---")

    pipeline_stepper = engine.compute_to_generator(total_steps)

    for i, state in enumerate(pipeline_stepper):
        print(
            f"\n[Step {i + 1}/{total_steps}] -> Executed: {state.operation_name}"
        )
        print(f"  - Line count: {len(state.lines)}")

        total_vertices = sum(len(line.coords) for line in state.lines)
        print(f"  - Total vertices: {total_vertices}")

        if i + 1 < total_steps:
            try:
                input(
                    "\nPress Enter to compute the next step (or Ctrl+C to quit)..."
                )
            except KeyboardInterrupt:
                print("\n\nExiting sandbox early.")
                sys.exit(0)

    print("\n--- Pipeline Complete ---")
    print(
        f"Engine history successfully cached {len(engine.store)} total state snapshots."
    )


if __name__ == "__main__":
    main()
