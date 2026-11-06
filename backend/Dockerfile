FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 YOLO_CONFIG_DIR=/tmp/Ultralytics
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt
# Il modello YOLO11s si scarica una volta qui, così l'app parte anche senza internet.
RUN mkdir -p models && python -c "from ultralytics import YOLO; YOLO('yolo11s.pt')" && mv yolo11s.pt models/
COPY *.py ./
EXPOSE 8001
# --proxy-headers: lo schema (https dietro Tailscale) e l'IP veri arrivano da nginx, l'unico che raggiunge il backend.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--ws-max-size", "4194304", "--proxy-headers", "--forwarded-allow-ips", "*"]
