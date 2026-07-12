import json
from typing import List, Literal, Union, Any
from pydantic import BaseModel, Field, RootModel, create_model

def generate_recipe_schema(registry: Any, output_path: str = "recipe-schema.json"):
    step_models = []

    for op_name, op_info in registry.items():
        ConfigClass = op_info["config"]

        if not ConfigClass:
            class EmptyConfig(BaseModel):
                pass
            ConfigClass = EmptyConfig

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

    RecipeType = List[Union[tuple(step_models)]]
    RecipeRoot = RootModel[RecipeType]
    schema_dict = RecipeRoot.model_json_schema()

    with open(output_path, "w") as f:
        json.dump(schema_dict, f, indent=2)

    print(f"Successfully generated recipe schema at: {output_path}")
