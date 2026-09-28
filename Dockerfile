# Runs the app only. Ollama stays on the host so it can use your GPU (Docker on Mac can't).
FROM python:3.12-slim
COPY requirements.txt main.py prefs.example.toml /app/
RUN pip install --no-cache-dir -r /app/requirements.txt
ENV OLLAMA_URL=http://host.docker.internal:11434
WORKDIR /data
ENTRYPOINT ["python", "/app/main.py"]
