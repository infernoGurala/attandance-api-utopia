FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=7860 \
    HOME=/home/user \
    PLAYWRIGHT_BROWSERS_PATH=/home/user/.cache/ms-playwright

WORKDIR /app

# Install basic system packages and xvfb for headful browser execution on headless server
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    xvfb \
    xauth \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    libcairo2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set up a new user named "user" with UID 1000
RUN useradd -m -u 1000 user

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create cache directory and set permissions
RUN mkdir -p /home/user/.cache && chown -R user:user /home/user

# Switch to the non-root user
USER user

# Install Patchright Chromium
RUN python -m patchright install chromium

# Copy app code and set ownership
COPY --chown=user:user . .

# Expose the default Hugging Face Spaces port
EXPOSE 7860

# Run FastAPI server under xvfb-run
CMD ["xvfb-run", "--server-args=-screen 0 1280x1024x24", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
