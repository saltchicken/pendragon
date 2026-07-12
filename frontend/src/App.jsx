import React, { useState, useRef, useEffect, useCallback } from 'react';
import './App.css';

export default function App() {
  const [recipe, setRecipe] = useState([
    { operation: "grid_lines", settings: { spacing: 5, orientation: "horizontal" } }
  ]);
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

  // Generate Toolpath
  const handleGenerate = useCallback(async () => {
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
        setError("Pipeline failed. Check server logs.");
      }
    } catch (err) {
      setError("Network error communicating with the API.");
    } finally {
      setIsGenerating(false);
    }
  }, [recipe]);

  // Live Auto-Update: Trigger generation when recipe changes (with basic debounce)
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      handleGenerate();
    }, 500); // 500ms debounce
    return () => clearTimeout(timeoutId);
  }, [recipe, handleGenerate]);

  // Handle Recipe Edits
  const updateOperationSetting = (opIndex, key, value) => {
    const newRecipe = [...recipe];
    // Attempt to cast numerics to allow smooth slider/number input integration
    const parsedValue = isNaN(value) || value === "" ? value : Number(value);
    newRecipe[opIndex].settings[key] = parsedValue;
    setRecipe(newRecipe);
  };

  const addOperation = () => {
    setRecipe([...recipe, { operation: "transform", settings: { translate_x: 0, translate_y: 0 } }]);
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
    
    // Auto-resize
    const parent = canvas.parentElement;
    canvas.width = parent.clientWidth;
    canvas.height = parent.clientHeight;
    
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    ctx.save();
    // Apply Camera Transform
    ctx.translate(camera.x, camera.y);
    ctx.scale(camera.scale, camera.scale);

    // 1. Draw Boundary
    if (boundary && boundary.length > 0) {
      ctx.beginPath();
      ctx.moveTo(boundary[0][0], boundary[0][1]);
      for (let i = 1; i < boundary.length; i++) {
        ctx.lineTo(boundary[i][0], boundary[i][1]);
      }
      ctx.strokeStyle = '#444444'; // Subtle grey for boundary
      ctx.lineWidth = 1 / camera.scale; // Keep line thin regardless of zoom
      ctx.setLineDash([5 / camera.scale, 5 / camera.scale]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // 2. Draw Vectors
    ctx.strokeStyle = '#aa3bff'; // Matching your index.css accent color
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

  return (
    <div className="app-layout">
      <div className="sidebar">
        <div className="sidebar-header">
          <h2>Pendragon</h2>
          <span className="status">{isGenerating ? 'Generating...' : 'Idle'}</span>
        </div>
        
        {error && <div className="error-banner">{error}</div>}
        
        <div className="recipe-list">
          {recipe.map((op, index) => (
            <div key={index} className="operation-card">
              <div className="op-header">
                <input 
                  className="op-title-input"
                  value={op.operation} 
                  onChange={(e) => {
                    const newRecipe = [...recipe];
                    newRecipe[index].operation = e.target.value;
                    setRecipe(newRecipe);
                  }}
                />
                <button className="icon-btn delete" onClick={() => removeOperation(index)}>✕</button>
              </div>
              <div className="op-settings">
                {Object.entries(op.settings).map(([key, val]) => (
                  <div className="setting-row" key={key}>
                    <label>{key}</label>
                    <input 
                      type="text" 
                      value={val} 
                      onChange={(e) => updateOperationSetting(index, key, e.target.value)} 
                    />
                  </div>
                ))}
              </div>
            </div>
          ))}
          <button className="add-op-btn" onClick={addOperation}>+ Add Operation</button>
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
