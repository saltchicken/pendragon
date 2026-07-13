import json
from typing import Literal, Union

from pydantic import BaseModel
from pydantic import create_model
from pydantic import Field
from pydantic import RootModel

from .discovery import load_plugins
from .registry import PluginRegistry


def generate_recipe_schema(output_path: str = "recipe-schema.json"):
    # Ensure all plugins are discovered and loaded into the registry
    load_plugins()

    registry = PluginRegistry()
    registry.discover()

    step_models = []

    for op_name, op_info in registry.operations.items():
        ConfigClass = op_info["config"]

        if not ConfigClass:

            class EmptyConfig(BaseModel):
                pass

            ConfigClass = EmptyConfig

        step_model = create_model(
            f"Step_{op_name.replace('-', '_')}",
            operation=(Literal[op_name],
                       Field(
                           description=f"Execute the '{op_name}' operation.")),
            settings=(ConfigClass,
                      Field(default_factory=dict,
                            description=f"Settings for '{op_name}'.")),
            __base__=BaseModel)
        step_models.append(step_model)

    if not step_models:
        print(
            "No operations found in registry. Make sure plugins are registering properly."
        )
        return

    RecipeType = list[Union[tuple(step_models)]]
    RecipeRoot = RootModel[RecipeType]
    schema_dict = RecipeRoot.model_json_schema()

    with open(output_path, "w") as f:
        json.dump(schema_dict, f, indent=2)

    print(f"Successfully generated recipe schema at: {output_path}")


if __name__ == "__main__":
    generate_recipe_schema()
