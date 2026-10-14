FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 HF_HOME=/hf-cache
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY server.py .
EXPOSE 7801
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7801", "--workers", "1"]
