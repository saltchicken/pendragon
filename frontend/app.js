document.getElementById('generateBtn').addEventListener('click', async () => {
    const recipeText = document.getElementById('recipeInput').value;
    let recipe;
    
    try {
        // Note: For version 1, parsing JSON is easiest. 
        // If you want to accept raw YAML in the browser, include a library like js-yaml
        recipe = JSON.parse(recipeText);
    } catch (e) {
        alert("Invalid JSON recipe");
        return;
    }

    const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe: recipe })
    });

    if (response.ok) {
        const data = await response.json();
        drawVectors(data.vectors);
        
        // Enable G-code download
        const dlBtn = document.getElementById('downloadBtn');
        dlBtn.disabled = false;
        dlBtn.onclick = () => downloadString(data.gcode, 'output.nc');
    } else {
        alert("Pipeline failed.");
    }
});

function drawVectors(vectors) {
    const canvas = document.getElementById('renderCanvas');
    const ctx = canvas.getContext('2d');
    
    // Setup canvas size based on window or bounding box
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = canvas.parentElement.clientHeight;
    
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = '#00ff00';
    ctx.lineWidth = 1;

    // Simple drawing loop (you will likely want to add scaling/panning logic here)
    vectors.forEach(path => {
        if (path.length === 0) return;
        ctx.beginPath();
        ctx.moveTo(path[0][0], path[0][1]);
        for (let i = 1; i < path.length; i++) {
            ctx.lineTo(path[i][0], path[i][1]);
        }
        ctx.stroke();
    });
}

function downloadString(text, filename) {
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}
