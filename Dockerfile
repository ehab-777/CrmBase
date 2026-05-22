FROM python:3.11.9-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    ffmpeg \
    libffi-dev \
    libjpeg-dev \
    libpng-dev \
    zlib1g-dev \
    libcairo2-dev \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    pkg-config \
    fonts-hosny-amiri \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# Copy application code
COPY . .

# Make init.sh executable
RUN chmod +x init.sh

# Data directory (mapped to Railway volume at /data)
RUN mkdir -p /data

EXPOSE 8000

CMD ["bash", "init.sh"]
