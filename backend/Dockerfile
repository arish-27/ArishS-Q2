FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Store HuggingFace / faster-whisper models outside /app so bind mounts don't shadow them
ENV HF_HOME=/opt/hf_cache

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download faster-whisper models (small.en for English + configurable WHISPER_MODEL_SIZE)
ARG WHISPER_MODEL_SIZE=small
ARG WHISPER_ENGLISH_MODEL_SIZE=small.en
ENV WHISPER_MODEL_SIZE=${WHISPER_MODEL_SIZE}
ENV WHISPER_ENGLISH_MODEL_SIZE=${WHISPER_ENGLISH_MODEL_SIZE}
RUN python -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['WHISPER_ENGLISH_MODEL_SIZE'], device='cpu', compute_type='int8'); WhisperModel(os.environ['WHISPER_MODEL_SIZE'], device='cpu', compute_type='int8')"

# Copy backend application source code
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Default command to run FastAPI development server with hot-reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
