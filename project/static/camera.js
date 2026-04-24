const startBtn = document.getElementById('btn-start');
const scanBtn = document.getElementById('btn-scan');
const submitBtn = document.getElementById('btn-submit');
const video = document.getElementById('video-feed');
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const notification = document.getElementById('notification');
const loadingIndicator = document.getElementById('loading-indicator');
const resultCard = document.getElementById('result-card');
const vehicleInput = document.getElementById('vehicle-number');
const confidenceScore = document.getElementById('confidence-score');
const targetBox = document.getElementById('target-box');


let stream = null;

// Initialize camera access
startBtn.addEventListener('click', async () => {
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: 'environment', // Prefer rear camera on mobile
                width: { ideal: 1280 },
                height: { ideal: 720 }
            }
        });
        
        video.srcObject = stream;
        startBtn.style.display = 'none';
        scanBtn.disabled = false;
        
        showNotification('Camera started successfully', 'success');
        
    } catch (err) {
        console.error("Error accessing camera:", err);
        showNotification(`Failed to access camera: ${err.message}`, 'error');
    }
});

// Capture frame and send to backend API
scanBtn.addEventListener('click', async () => {
    if (!stream) return;
    
    // UI changes during scan
    scanBtn.disabled = true;
    loadingIndicator.style.display = 'block';
    targetBox.classList.remove('success');
    resultCard.style.display = 'none';
    
    try {
        // Set canvas to video dimensions
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        
        // Draw current video frame onto canvas
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        
        // Convert to base64 JPEG format
        const imageData = canvas.toDataURL('image/jpeg', 0.8);
        
        showNotification('Image captured, analyzing...', 'info');
        
        // Send to backend endpoint
        const response = await fetch('/api/scan', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ image: imageData })
        });
        
        const data = await response.json();
        
        if (data.success) {
            targetBox.classList.add('success');
            
            // Show result card
            resultCard.style.display = 'block';
            vehicleInput.value = data.vehicle_number;
            
            const confPercent = Math.round(data.confidence * 100);
            confidenceScore.textContent = confPercent;
            
            // Highlight low confidence
            if (confPercent < 60) {
                confidenceScore.style.color = '#ef4444'; // red
            } else if (confPercent < 85) {
                confidenceScore.style.color = '#eab308'; // yellow
            } else {
                confidenceScore.style.color = '#10b981'; // green
            }
            
            showNotification('Plate detected successfully!', 'success');
        } else {
            showNotification(`Detection failed: ${data.error}`, 'error');
        }
        
    } catch (err) {
        console.error("Scanning error:", err);
        showNotification(`Error during scan: ${err.message}`, 'error');
    } finally {
        // Re-enable tools after response
        scanBtn.disabled = false;
        loadingIndicator.style.display = 'none';
    }
});

// Submit detected plate to DB via backend
submitBtn.addEventListener('click', async () => {
    const vn = vehicleInput.value.trim().toUpperCase();
    
    if (!vn) {
        showNotification('Please enter a vehicle number', 'error');
        return;
    }
    
    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting...';
    
    try {
        const response = await fetch('/api/submit_entry', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                vehicle_number: vn,
                phone_number: "0000000000" // Default scanner phone
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Entry saved successfully! Allocating Slot...', 'success');
            
            // Redirect to the success ledger screen (slot allocation)
            if (data.redirect) {
                setTimeout(() => {
                    window.location.href = data.redirect;
                }, 1000);
            } else {
                // reset UI if no redirect
                resultCard.style.display = 'none';
                vehicleInput.value = '';
                targetBox.classList.remove('success');
            }
            
            // Optional: stop stream after success
            // stopStream(); 
        } else {
            showNotification(`Failed to save: ${data.error}`, 'error');
        }
    } catch (err) {
        console.error("Submission error:", err);
        showNotification(`Error saving entry: ${err.message}`, 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit Entry';
    }
});

// Utility fn to display generic styled notifications
function showNotification(msg, type='info') {
    notification.textContent = msg;
    notification.className = 'alert'; // reset classes
    
    if (type === 'error') {
        notification.classList.add('alert-error');
        notification.style.backgroundColor = '#fee2e2';
        notification.style.color = '#991b1b';
        notification.style.border = '1px solid #fecaca';
    } else if (type === 'success') {
        notification.style.backgroundColor = '#d1fae5';
        notification.style.color = '#065f46';
        notification.style.border = '1px solid #a7f3d0';
    } else {
        notification.style.backgroundColor = '#e0f2fe';
        notification.style.color = '#0369a1';
        notification.style.border = '1px solid #bae6fd';
    }
    
    notification.style.display = 'block';
    
    // Auto-hide after 5s
    setTimeout(() => {
        notification.style.display = 'none';
    }, 5000);
}

// Clean up resources if navigating away
window.addEventListener('beforeunload', stopStream);

function stopStream() {
    if (stream) {
        stream.getTracks().forEach(track => track.stop());
        stream = null;
    }
}
