import React, { useState, useRef, useEffect, useCallback } from 'react';
import './App.css';

export default function App() {
  const [recipe, setRecipe] = useState([]);
  const [availableOps, setAvailableOps] = useState({});
  const [gcode, setGcode] = useState(null);
  const [vectors, setVectors] = useState([]);
  const [boundary, setBoundary] = useState([]);
  const [error, setError] = useState(null);
  const [isGenerating, setIsGenerating] = useState(false);

  // Viewport/Camera State
  const canvasRef = useRef(null);
  const [camera, setCamera] = useState({ x: 50, y: 50, scale: 2 });
  const isDragging = useRef(false);
  const lastMouse = useRef({ x: 0, y: 0 });

  // --- Initialize App & Fetch Schemas ---
  useEffect(() => {
    fetch('/api/schema')
      .then(res => res.json())
      .then(data => {
        setAvailableOps(data);
        // Load a default recipe once schemas are ready if recipe is empty
        if (recipe.length === 0 && Object.keys(data).length > 0) {
          setRecipe([{ operation: "grid_lines", settings: { spacing: 5, orientation: "horizontal" } }]);
        }
      })
      .catch(err => console.error("Failed to fetch schema:", err));
  }, []);

  // --- Generate Toolpath ---
  const handleGenerate = useCallback(async () => {
    if (recipe.length === 0) return;
    setIsGenerating(true);
    setError(null);
    try {
      const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe })
      });

      if (response.ok) {
        const data = await response.json();
        setVectors(data.vectors);
        setBoundary(data.boundary);
        setGcode(data.gcode);
      } else {
        setError("Pipeline failed. Check server logs for schema validation errors.");
      }
    } catch (err) {
      setError("Network error communicating with the API.");
    } finally {
      setIsGenerating(false);
    }
  }, [recipe]);

  // Live Auto-Update
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      handleGenerate();
    }, 400); 
    return () => clearTimeout(timeoutId);
  }, [recipe, handleGenerate]);

  // --- Recipe Manipulation ---
  const updateOperationSetting = (opIndex, key, value, type) => {
    const newRecipe = [...recipe];
    let parsedValue = value;
    
    if (type === 'number' || type === 'integer') {
      parsedValue = value === "" ? "" : Number(value);
    } else if (type === 'boolean') {
      parsedValue = value; 
    } else if (type === 'object') {
      // Try to parse it as JSON if it's an object field
      try {
        parsedValue = JSON.parse(value);
      } catch(e) {
        // If they are halfway through typing valid JSON, leave it as a string.
        // The backend will reject it until they finish typing the valid JSON.
        parsedValue = value;
      }
    }

    newRecipe[opIndex].settings[key] = parsedValue;
    setRecipe(newRecipe);
  };

  const addOperation = (opName) => {
    if (!opName) return;
    const schema = availableOps[opName];
    const defaultSettings = {};
    
    // Auto-populate default values based on Pydantic schema
    if (schema && schema.properties) {
      Object.entries(schema.properties).forEach(([key, prop]) => {
        if (prop.default !== undefined) {
          defaultSettings[key] = prop.default;
        } else if (prop.type === 'number' || prop.type === 'integer') {
          defaultSettings[key] = 0;
        } else if (prop.type === 'boolean') {
          defaultSettings[key] = false;
        } else if (prop.type === 'object') {
          defaultSettings[key] = {};
        } else {
          defaultSettings[key] = "";
        }
      });
    }
    
    setRecipe([...recipe, { operation: opName, settings: defaultSettings }]);
  };

  const removeOperation = (index) => {
    setRecipe(recipe.filter((_, i) => i !== index));
  };

  const handleDownload = () => {
    if (!gcode) return;
    const blob = new Blob([gcode], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'pendragon_output.nc';
    a.click();
    URL.revokeObjectURL(url);
  };

  // --- Canvas Interaction Handlers ---
  const handleWheel = (e) => {
    e.preventDefault();
    const zoomSensitivity = 0.002;
    const delta = -e.deltaY * zoomSensitivity;
    setCamera(prev => ({
      ...prev,
      scale: Math.max(0.1, Math.min(prev.scale * Math.exp(delta), 20))
    }));
  };

  const handlePointerDown = (e) => {
    isDragging.current = true;
    lastMouse.current = { x: e.clientX, y: e.clientY };
  };

  const handlePointerMove = (e) => {
    if (!isDragging.current) return;
    const dx = e.clientX - lastMouse.current.x;
    const dy = e.clientY - lastMouse.current.y;
    setCamera(prev => ({ ...prev, x: prev.x + dx, y: prev.y + dy }));
    lastMouse.current = { x: e.clientX, y: e.clientY };
  };

  const handlePointerUp = () => {
    isDragging.current = false;
  };

  // --- Canvas Rendering ---
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    const parent = canvas.parentElement;
    canvas.width = parent.clientWidth;
    canvas.height = parent.clientHeight;
    
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    ctx.save();
    ctx.translate(camera.x, camera.y);
    ctx.scale(camera.scale, camera.scale);

    // Draw Boundary
    if (boundary && boundary.length > 0) {
      ctx.beginPath();
      ctx.moveTo(boundary[0][0], boundary[0][1]);
      for (let i = 1; i < boundary.length; i++) {
        ctx.lineTo(boundary[i][0], boundary[i][1]);
      }
      ctx.strokeStyle = '#444444'; 
      ctx.lineWidth = 1 / camera.scale; 
      ctx.setLineDash([5 / camera.scale, 5 / camera.scale]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Draw Vectors
    ctx.strokeStyle = '#aa3bff'; 
    ctx.lineWidth = 1.5 / camera.scale;

    vectors.forEach(path => {
      if (path.length === 0) return;
      ctx.beginPath();
      ctx.moveTo(path[0][0], path[0][1]);
      for (let i = 1; i < path.length; i++) {
        ctx.lineTo(path[i][0], path[i][1]);
      }
      ctx.stroke();
    });
    
    ctx.restore();
  }, [vectors, boundary, camera]);

  // --- Helper to render dynamic inputs ---
  const renderDynamicInput = (opIndex, key, val, schemaProp) => {
    if (!schemaProp) return <input type="text" value={val} onChange={(e) => updateOperationSetting(opIndex, key, e.target.value, 'string')} />;

    // Boolean Checkbox
    if (schemaProp.type === 'boolean') {
      return (
        <input 
          type="checkbox" 
          checked={!!val} 
          onChange={(e) => updateOperationSetting(opIndex, key, e.target.checked, 'boolean')} 
        />
      );
    }

    // Dropdown for Enum/Literal (FastAPI/Pydantic exports literals inside 'anyOf' or 'enum')
    const enumValues = schemaProp.enum || (schemaProp.anyOf && schemaProp.anyOf.map(a => a.const).filter(Boolean));
    if (enumValues && enumValues.length > 0) {
      return (
        <select value={val} onChange={(e) => updateOperationSetting(opIndex, key, e.target.value, 'string')}>
          {enumValues.map(opt => <option key={opt} value={opt}>{opt}</option>)}
        </select>
      );
    }

    // Number/Float inputs
    if (schemaProp.type === 'number' || schemaProp.type === 'integer') {
      return (
        <input 
          type="number" 
          step="any" 
          value={val} 
          onChange={(e) => updateOperationSetting(opIndex, key, e.target.value, schemaProp.type)} 
        />
      );
    }

    if (schemaProp.type === 'object') {
      // Stringify it for the input field so it's readable/editable
      const strValue = typeof val === 'object' ? JSON.stringify(val) : val;
      return (
        <input 
          type="text" 
          value={strValue} 
          onChange={(e) => updateOperationSetting(opIndex, key, e.target.value, 'object')}
          placeholder="{}" 
        />
      );
    }

    // Default String
    return (
      <input 
        type="text" 
        value={val} 
        onChange={(e) => updateOperationSetting(opIndex, key, e.target.value, 'string')} 
      />
    );
  };

  return (
    <div className="app-layout">
      <div className="sidebar">
        <div className="sidebar-header">
          <h2>Pendragon</h2>
          <span className="status">{isGenerating ? 'Generating...' : 'Idle'}</span>
        </div>
        
        {error && <div className="error-banner">{error}</div>}
        
        <div className="recipe-list">
          {recipe.map((op, index) => {
            const opSchema = availableOps[op.operation]?.properties || {};
            return (
              <div key={index} className="operation-card">
                <div className="op-header">
                  <span className="op-title">{op.operation}</span>
                  <button className="icon-btn delete" onClick={() => removeOperation(index)}>✕</button>
                </div>
                <div className="op-settings">
                  {Object.entries(op.settings).map(([key, val]) => (
                    <div className="setting-row" key={key} title={opSchema[key]?.description || ''}>
                      <label>{key}</label>
                      {renderDynamicInput(index, key, val, opSchema[key])}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
          
          <select 
            className="add-op-dropdown" 
            value=""
            onChange={(e) => addOperation(e.target.value)}
          >
            <option value="" disabled>+ Add Operation...</option>
            {Object.keys(availableOps).sort().map(opName => (
              <option key={opName} value={opName}>{opName}</option>
            ))}
          </select>

        </div>

        <div className="button-group">
          <button disabled={!gcode} onClick={handleDownload}>
            Download G-Code
          </button>
        </div>
      </div>
      
      <div className="viewer">
        <canvas 
          ref={canvasRef} 
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
        />
        <div className="canvas-hints">Scroll to zoom • Click & drag to pan</div>
      </div>
    </div>
  );
}
