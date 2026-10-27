# ---- frontend build ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG VITE_CONTACT_EMAIL=""
ENV VITE_CONTACT_EMAIL=$VITE_CONTACT_EMAIL
RUN npm run build

# ---- runtime ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# Strip Windows line endings (octal 015 = CR) so the script runs on Linux; create the app user.
RUN tr -d '\015' < /usr/local/bin/docker-entrypoint.sh > /tmp/ep \
    && mv /tmp/ep /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd --create-home gradient && mkdir -p data && chown -R gradient /app
# Starts as root only to chown mounted volumes, then drops to the `gradient` user.
ENTRYPOINT ["docker-entrypoint.sh"]
EXPOSE 8270
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8270'))"
# Same image runs the standalone worker: `python -m gradient.cli worker`
# Listens on $PORT when the host sets it (Railway, Render), else 8270.
CMD ["python", "-m", "gradient.cli", "serve", "--host", "0.0.0.0"]
