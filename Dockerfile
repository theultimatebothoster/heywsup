FROM python:3.11-slim

# Install system dependencies (including build essentials and Opus for music voice streaming)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run the dual startup script
CMD ["python", "start.py"]