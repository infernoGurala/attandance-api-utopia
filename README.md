# Utopia Attendance API Server & WebUI

A high-performance FastAPI server and gorgeous glassmorphic WebUI for fetching and parsing student attendance details from the `info.aec.edu.in` college portal. Designed for local execution and seamless deployment to **Hugging Face Spaces** (via Docker).

## Features

- **Standard Login (100% Automated & Bypasses Cloudflare)**: Provide credentials, and the server automatically launches a headful browser using `patchright` inside a virtual display frame (`xvfb-run`), encrypts the password using the portal's AES key, performs human-like coordinate mouse clicks to solve the Cloudflare Turnstile checkbox, logs in, and extracts the attendance.
- **Direct Cookie Bypass (Instant)**: Pass active session cookies (`ASP.NET_SessionId` and `frmAuth`) from your client app to query the attendance table instantly. This is sub-second fast and completely avoids launching any browser on the server.
- **Consolidated & Subject-wise Bunk Health Calculator**: Automatically computes whether you are safe to bunk classes (and how many) or how many consecutive classes you must attend to maintain or reach the 75% attendance threshold.
- **Interactive UI**: Sleek dark mode dashboard built with glassmorphism, dynamic progress indicators, and responsive stats.
- **Dockerized & HF-Ready**: Ready to be uploaded directly to Hugging Face Spaces.

---

## API Documentation

### Fetch Attendance
- **Endpoint**: `POST /api/attendance`
- **Headers**: `Content-Type: application/json`

#### Request Payload Examples

##### Option A: Standard Login (Automated)
```json
{
  "roll_number": "21A91A1201",
  "password": "your_portal_password",
  "college": "aus",
  "mode": "tillNow"
}
```

##### Option B: Cookie Bypass (Instant)
```json
{
  "roll_number": "21A91A1201",
  "college": "aus",
  "cookies": {
    "ASP.NET_SessionId": "xyz...",
    "frmAuth": "abc..."
  }
}
```

---

## How to Run Locally

### 1. Manual Setup
Create a Python virtual environment and install dependencies:

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Patchright Chromium browser
python3 -m patchright install chromium
```

Start the FastAPI server inside `xvfb-run` (so that headful browser works headlessly on your machine):
```bash
xvfb-run python3 main.py
```
Open `http://localhost:8000` in your web browser.

### 2. Docker Setup
Build and run the container locally:

```bash
docker build -t attendance-api .
docker run -p 8000:7860 attendance-api
```
Open `http://localhost:8000` in your web browser.

---

## Deploy to Hugging Face Spaces

1. Create a new Space on [Hugging Face](https://huggingface.co/new-space).
2. Set the **SDK** type to **Docker**.
3. Upload all the files from this directory (`main.py`, `scraper.py`, `requirements.txt`, `Dockerfile`, `static/`, `README.md`) to the repository.
4. Hugging Face will automatically build the image using the provided `Dockerfile` and spin up your server on port `7860` (which is mapped to the public Space URL). It runs under `xvfb-run` internally, enabling automatic headful Turnstile solving in the cloud.
