FROM python:3.11-slim

WORKDIR /app

# Install only required LibreOffice components (not full suite)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-core \
    libreoffice-common \
    fonts-dejavu-core \
    fonts-liberation \
    libpoppler-cpp-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements FIRST (Docker cache optimization)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files AFTER pip install
COPY . .

RUN mkdir -p /app/uploads/previews /app/uploads/temp

ENV PORT=10000
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp
ENV TMPDIR=/tmp

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--timeout", "180", "--no-sendfile", "web_interface.app:app", "--bind", "0.0.0.0:10000"]