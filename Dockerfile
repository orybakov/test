FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sentinel ./sentinel
COPY static ./static
EXPOSE 8099
CMD ["uvicorn", "sentinel.app:app", "--host", "0.0.0.0", "--port", "8099", "--workers", "1"]
