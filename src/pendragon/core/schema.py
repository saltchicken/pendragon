import json
from pathlib import Path
from typing import List, Literal, Union
from pydantic import BaseModel, Field, create_model, RootModel  # <-- Import RootModel

from pendragon.core.discovery import load_plugins
from pendragon.core.registry import OPERATION_REGISTRY


def generate_recipe_schema(output_path: str = "recipe-schema.json"):
    # Ensure all plugins are discovered and loaded into the registry
    load_plugins()

    step_models = []

    for op_name, op_info in OPERATION_REGISTRY.items():
        ConfigClass = op_info["config"]
        
        # Fallback to an empty base model if the plugin doesn't define custom settings
        if not ConfigClass:
            class EmptyConfig(BaseModel):
                pass
            ConfigClass = EmptyConfig

        # Create a specific Pydantic model for this operation step
        step_model = create_model(
            f"Step_{op_name.replace('-', '_')}",
            operation=(Literal[op_name], Field(description=f"Execute the '{op_name}' operation.")),
            settings=(ConfigClass, Field(default_factory=dict, description=f"Settings for '{op_name}'.")),
            __base__=BaseModel
        )
        step_models.append(step_model)

    if not step_models:
        print("No operations found in registry. Make sure plugins are registering properly.")
        return

    # In Pydantic V2, construct a Union hint by unpacking the models: Union[ModelA, ModelB, ...]
    RecipeType = List[Union[tuple(step_models)]]

    # Use RootModel to wrap the top-level list array type cleanly
    RecipeRoot = RootModel[RecipeType]

    # Generate the JSON schema using V2's model_json_schema() method
    schema_dict = RecipeRoot.model_json_schema()
    
    with open(output_path, "w") as f:
        json.dump(schema_dict, f, indent=2)
        
    print(f"Successfully generated recipe schema at: {output_path}")

if __name__ == "__main__":
    generate_recipe_schema()
