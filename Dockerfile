# Base Python image
FROM python:3.11-slim

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

# Install system dependencies for LibreOffice + fonts
RUN apt-get update && apt-get install -y \
    libreoffice \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    fonts-dejavu \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (better Docker caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy remaining project files
COPY . .

# Expose port (Render requirement)
EXPOSE 10000

# Start Gunicorn (SocketIO compatible + no sendfile bug fix)
CMD ["gunicorn", "web_interface.app:app", "--bind", "0.0.0.0:10000", "--workers", "1", "--worker-class", "eventlet", "--no-sendfile", "--timeout", "180"]

