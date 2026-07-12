import React, { useState, useRef, useEffect } from 'react';
import './App.css';

export default function App() {
  const [recipeText, setRecipeText] = useState('[\n  {\n    "operation": "grid_lines",\n    "settings": {\n      "spacing": 5,\n      "orientation": "horizontal"\n    }\n  }\n]');
  const [gcode, setGcode] = useState(null);
  const [vectors, setVectors] = useState([]);
  const [error, setError] = useState(null);
  const canvasRef = useRef(null);

  const handleGenerate = async () => {
    setError(null);
    let recipe;

    try {
      recipe = JSON.parse(recipeText);
    } catch (e) {
      setError("Invalid JSON recipe format.");
      return;
    }

    try {
      const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe })
      });

      if (response.ok) {
        const data = await response.json();
        setVectors(data.vectors);
        setGcode(data.gcode);
      } else {
        setError("Pipeline failed. Check server logs.");
      }
    } catch (err) {
      setError("Network error communicating with the API.");
    }
  };

  const handleDownload = () => {
    if (!gcode) return;
    const blob = new Blob([gcode], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'output.nc';
    a.click();
    URL.revokeObjectURL(url);
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    // Scale canvas to parent container
    const parent = canvas.parentElement;
    canvas.width = parent.clientWidth;
    canvas.height = parent.clientHeight;
    
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = '#00ff00';
    ctx.lineWidth = 1;

    vectors.forEach(path => {
      if (path.length === 0) return;
      ctx.beginPath();
      ctx.moveTo(path[0][0], path[0][1]);
      for (let i = 1; i < path.length; i++) {
        ctx.lineTo(path[i][0], path[i][1]);
      }
      ctx.stroke();
    });
  }, [vectors]);

  return (
    <div className="app-layout">
      <div className="sidebar">
        <h2>Pendragon</h2>
        {error && <div className="error-banner">{error}</div>}
        <textarea 
          value={recipeText} 
          onChange={(e) => setRecipeText(e.target.value)} 
          placeholder="Paste JSON recipe here..."
        />
        <div className="button-group">
          <button onClick={handleGenerate}>Generate</button>
          <button disabled={!gcode} onClick={handleDownload}>
            Download G-Code
          </button>
        </div>
      </div>
      
      <div className="viewer">
        <canvas ref={canvasRef} />
      </div>
    </div>
  );
}
