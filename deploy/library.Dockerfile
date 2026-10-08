FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LIBRARY_DATA_DIR=/var/lib/zhixi-library
WORKDIR /app
COPY requirements-library.txt ./
RUN pip install --no-cache-dir -r requirements-library.txt \
    && useradd --uid 10001 --create-home library \
    && mkdir -p /var/lib/zhixi-library \
    && chown library:library /var/lib/zhixi-library
COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist/
USER library
EXPOSE 8001
CMD ["python", "-m", "uvicorn", "backend.library.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
