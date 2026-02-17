# Base Python image
FROM python:3.11-slim

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

# Copy project files 
COPY . .


# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt


# Expose port (Render requirement)
EXPOSE 10000


# Start Gunicorn (SocketIO compatible + no sendfile bug fix)
CMD ["gunicorn", "--workers", "1", "--worker-class", "eventlet", "--timeout", "180", "--bind", "0.0.0.0:10000", "--no-sendfile", "web_interface.app:app"]


