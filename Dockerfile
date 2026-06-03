# 6DE Company Platform — production image
#
# Build:  docker build -t 6de-platform .
# Run:    docker run -p 8000:8000 \
#           -e DB_BACKEND=sqlite \
#           -e PLATFORM_DB_PATH=/data/platform.db \
#           -v 6de_data:/data \
#           6de-platform
#
# Auth: sign-in is handled by Azure App Service Easy Auth (Entra ID) in
# production; there is NO credential file to mount. AUTH_CONFIG_PATH is optional
# (engineer profile only) and defaults to a repo-relative path — see config.py.
#
# On Azure App Service (Phase 8): persistent data moves to Azure Database for
# PostgreSQL flexible server + Azure Blob Storage; auth and connection secrets
# are mounted from Azure Key Vault via the App Service managed identity;
# DB_BACKEND will flip to "postgres" with PLATFORM_DATABASE_URL pointing at the
# Azure Postgres server.

FROM python:3.12-slim

# System deps: build-essential for wheels that need compilation;
# ca-certificates for HTTPS to Stripe / Graph / Azure.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code (Dockerignore strips _research, _archive, .git, etc.)
COPY . .

# Container-internal defaults — overridable at run time.
# No AUTH_CONFIG_PATH here: login is Azure Easy Auth, not a mounted YAML file.
ENV DB_BACKEND=sqlite \
    PLATFORM_DB_PATH=/data/platform.db \
    STREAMLIT_SERVER_PORT=8000 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Persistent data lives on a mounted volume
RUN mkdir -p /data

EXPOSE 8000

# Lightweight healthcheck — Streamlit's own /_stcore/health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/_stcore/health || exit 1

CMD ["streamlit", "run", "streamlit_app/Home.py", \
     "--server.port=8000", "--server.address=0.0.0.0"]
