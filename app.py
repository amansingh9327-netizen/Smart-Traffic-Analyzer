"""
TrafficSense v2 — Flask Backend
================================
Handles:
  - Traffic level detection (high / medium / low)
  - Ambulance detection in traffic → turns signal GREEN
  - Accident detection → turns signal GREEN + sends alert to hospital

Run:
  python app.py

Requires:
  pip install flask flask-cors pillow ultralytics twilio

NOTE: Replace the placeholder model paths and Twilio credentials below.
"""

import os
import io
import base64
import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image

from twilio.rest import Client
TWILIO_SID   = "AC2108e16d235b8f316e2d431cf8912a15"
TWILIO_TOKEN = "992d1a5244b4752a2676622aff52b1c4"
TWILIO_FROM  = "+16624304612"   # your Twilio number
HOSPITAL_NUMBER = "+919816980833"  # nearby hospital number
twilio_client = Client(TWILIO_SID, TWILIO_TOKEN)


app = Flask(__name__)
CORS(app)   # allow frontend (browser) to call this API

# ── Alert log (in-memory, resets on restart) ──────────────────────────────────
alert_log = []

# =============================================================================
# SECTION 1 — YOUR MODEL INTEGRATION
# =============================================================================
# Replace this section with your actual model.
# Your model's predict() must return a dict like:
#   {
#     "level":      "high" | "medium" | "low",
#     "ambulance":  True | False,
#     "accident":   True | False,
#     "confidence": 0.0 – 1.0
#   }
# =============================================================================

def run_model(image: Image.Image) -> dict:
    """
    Plug your trained model in here.
    ─────────────────────────────────
    Example using YOLOv8 (ultralytics):

        from ultralytics import YOLO
        model = YOLO("best.pt")          # your trained weights
        results = model(image)
        classes_detected = [model.names[int(c)] for c in results[0].boxes.cls]

        ambulance = "ambulance" in classes_detected
        accident  = "accident"  in classes_detected
        # Count vehicles for traffic level
        vehicle_count = sum(1 for c in classes_detected if c in ["car","truck","bus","motorbike"])
        level = "high" if vehicle_count > 15 else "medium" if vehicle_count > 5 else "low"
        confidence = float(results[0].boxes.conf.mean()) if len(results[0].boxes) else 0.5
        return {"level": level, "ambulance": ambulance, "accident": accident, "confidence": confidence}

    ─── DEMO STUB (remove when your model is ready) ────────────────────────────
    """
    import random
    # DEMO: randomly simulate detection for testing
    scenarios = [
        {"level": "high",   "ambulance": False, "accident": False, "confidence": 0.91},
        {"level": "medium", "ambulance": False, "accident": False, "confidence": 0.78},
        {"level": "low",    "ambulance": False, "accident": False, "confidence": 0.85},
        {"level": "high",   "ambulance": True,  "accident": False, "confidence": 0.94},  # ambulance
        {"level": "medium", "ambulance": False, "accident": True,  "confidence": 0.88},  # accident
    ]
    return random.choice(scenarios)


# =============================================================================
# SECTION 2 — HOSPITAL ALERT
# =============================================================================

def send_hospital_alert(alert_type: str, image_name: str) -> dict:
    """
    Send an SMS/alert to the nearby government hospital.
    Returns a dict with status info.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_body = (
        f"[TrafficSense ALERT] {timestamp}\n"
        f"Type: {alert_type}\n"
        f"Image: {image_name}\n"
        f"Action: Emergency services required immediately.\n"
        f"Signal has been turned GREEN for priority clearance."
    )

    # Log locally always
    alert_entry = {
        "type":      alert_type,
        "image":     image_name,
        "timestamp": timestamp,
        "message":   message_body,
        "status":    "logged"
    }

    try:
        twilio_client.messages.create(
            body=message_body,
            from_=TWILIO_FROM,
            to=HOSPITAL_NUMBER
        )
        alert_entry["status"] = "SMS sent"
    except Exception as e:
        alert_entry["status"] = f"SMS failed: {str(e)}"

    alert_log.append(alert_entry)
    print(f"\n🚨 ALERT SENT: {alert_type} | {timestamp}")
    print(f"   Message: {message_body}\n")
    return alert_entry


# =============================================================================
# SECTION 3 — ROUTES
# =============================================================================

@app.route('/predict', methods=['POST'])
def predict():
    """
    POST /predict
    Form-data: { image: <file> }

    Response JSON:
    {
      "signal":     "green" | "amber" | "red",
      "level":      "high" | "medium" | "low",
      "ambulance":  true | false,
      "accident":   true | false,
      "confidence": 0.0 – 1.0,
      "reason":     "string explaining why signal is green/amber/red",
      "alert":      null | { type, timestamp, status, message }
    }
    """
    if 'image' not in request.files:
        return jsonify({"error": "No image file provided. Use key 'image'."}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "Empty filename."}), 400

    try:
        image = Image.open(io.BytesIO(file.read())).convert("RGB")
    except Exception as e:
        return jsonify({"error": f"Cannot open image: {str(e)}"}), 400

    # Run your model
    result = run_model(image)

    level      = result.get("level",      "low")
    ambulance  = result.get("ambulance",  False)
    accident   = result.get("accident",   False)
    confidence = result.get("confidence", 0.5)

    alert_info = None

    # ── SIGNAL LOGIC ──────────────────────────────────────────────────────────
    if ambulance:
        signal = "green"
        reason = "🚑 Ambulance detected in traffic — signal forced GREEN for emergency clearance."

    elif accident:
        signal = "green"
        reason = "🚨 Road accident detected — signal forced GREEN & emergency alert sent to hospital."
        alert_info = send_hospital_alert("ROAD ACCIDENT", file.filename)

    elif level == "high":
        signal = "green"
        reason = "🟢 High traffic volume detected — signal is GREEN."

    elif level == "medium":
        signal = "amber"
        reason = "🟡 Moderate traffic detected — signal is AMBER."

    else:
        signal = "red"
        reason = "🔴 Low or no traffic detected — signal is RED."
    # ─────────────────────────────────────────────────────────────────────────

    return jsonify({
        "signal":     signal,
        "level":      level,
        "ambulance":  ambulance,
        "accident":   accident,
        "confidence": round(confidence, 3),
        "reason":     reason,
        "alert":      alert_info
    })


@app.route('/alerts', methods=['GET'])
def get_alerts():
    """GET /alerts — returns all logged emergency alerts."""
    return jsonify({"alerts": alert_log, "count": len(alert_log)})


@app.route('/health', methods=['GET'])
def health():
    """GET /health — check if server is running."""
    return jsonify({"status": "ok", "timestamp": datetime.datetime.now().isoformat()})


# =============================================================================
if __name__ == '__main__':
    print("=" * 55)
    print("  TrafficSense v2 — Backend Starting")
    print("=" * 55)
    print("  Endpoints:")
    print("    POST http://localhost:5000/predict")
    print("    GET  http://localhost:5000/alerts")
    print("    GET  http://localhost:5000/health")
    print("=" * 55)
    app.run(debug=True, port=5000)