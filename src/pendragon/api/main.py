import os
import tempfile
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Any

from pendragon.engine import PendragonEngine, load_plugins
from pendragon.pen import PenConfig, PenTool

app = FastAPI(title="Pendragon API")

# Mount the frontend directory to serve the web app
app.mount("/app", StaticFiles(directory="frontend/dist", html=True), name="frontend")

class GenerateRequest(BaseModel):
    recipe: List[dict]

@app.post("/api/generate")
async def generate_toolpath(req: GenerateRequest):
    load_plugins()
    
    # Initialize engine (headless mode)
    engine = PendragonEngine(recipe=req.recipe, interactive=False)
    
    if not engine.build_pipeline():
        raise HTTPException(status_code=400, detail="Failed to build pipeline. Check recipe schema.")
    
    # Run the engine
    final_lines = engine.run()
    
    # Format coordinate data for the frontend canvas to render
    # Converting Shapely LineStrings to simple nested lists: [ [x, y], [x, y] ]
    vector_data = []
    for line in final_lines:
        vector_data.append(list(line.coords))
        
    # Generate the G-Code into a temporary string/file
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
        "vectors": vector_data,
        "gcode": gcode_str
    }
