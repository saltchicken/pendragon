import os
import tempfile
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List

from pendragon.engine import PendragonEngine, load_plugins
from pendragon.engine.registry import OPERATION_REGISTRY
from pendragon.pen import PenConfig, PenTool

app = FastAPI(title="Pendragon API")
app.mount("/app", StaticFiles(directory="frontend/dist", html=True), name="frontend")

class GenerateRequest(BaseModel):
    recipe: List[dict]

@app.get("/api/schema")
async def get_schema():
    """Returns the JSON schema for all registered operations."""
    load_plugins()
    schema_data = {}
    
    for op_name, op_info in OPERATION_REGISTRY.items():
        ConfigClass = op_info["config"]
        if ConfigClass:
            # Pydantic v2 schema generation
            schema_data[op_name] = ConfigClass.model_json_schema()
        else:
            schema_data[op_name] = {"properties": {}}
            
    return schema_data

@app.post("/api/generate")
async def generate_toolpath(req: GenerateRequest):
    load_plugins()
    
    engine = PendragonEngine(recipe=req.recipe, interactive=False)
    
    if not engine.build_pipeline():
        raise HTTPException(status_code=400, detail="Failed to build pipeline.")
    
    final_lines = engine.run()
    
    # Extract Vector Data
    vector_data = [list(line.coords) for line in final_lines]
    
    # Extract Boundary Data from the initial state
    boundary_coords = []
    if engine.runner.initial_state.boundary:
        # Get the exterior ring coordinates of the boundary polygon
        boundary_coords = list(engine.runner.initial_state.boundary.exterior.coords)

    # Generate G-Code
    gcode_str = ""
    if final_lines:
        config = PenConfig()
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.nc') as tmp:
            tmp_name = tmp.name
            
        with PenTool(config=config, output_filename=tmp_name) as pen:
            for line in final_lines:
                pen.draw_path(list(line.coords))
                
        with open(tmp_name, 'r') as tmp:
            gcode_str = tmp.read()
        os.remove(tmp_name)

    return {
        "status": "success",
        "boundary": boundary_coords,
        "vectors": vector_data,
        "gcode": gcode_str
    }
