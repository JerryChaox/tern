# Read-only online copy of Tern. The database is pushed in by the edge Worker from R2.
FROM python:3.12-slim
WORKDIR /app
COPY tern/ tern/
COPY web/ web/
ENV TERN_HOST=0.0.0.0 TERN_PORT=8787 TERN_READONLY=1 TERN_DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8787
CMD ["python", "-m", "tern"]
