FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    tesseract-ocr \
    tesseract-ocr-eng \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p storage/uploads storage/reports storage/vector

EXPOSE 8000
CMD ["python", "app.py"]
