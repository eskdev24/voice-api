# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for PyDub (ffmpeg) and SpeechRecognition
RUN apt-get update && apt-get install -y \
    ffmpeg \
    flac \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port
EXPOSE 5000

# Run the application with Gunicorn
# 4 workers, binding to 0.0.0.0:$PORT (Render sets $PORT)
CMD gunicorn --workers 4 --bind 0.0.0.0:$PORT server:app
