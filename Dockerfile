# Use a fixed Debian release instead of the volatile Debian testing image.
# This avoids Playwright install failures caused by deprecated font packages in the trixie default.
FROM python:3.12-slim-bookworm

# Keep Python output unbuffered and avoid interactive apt prompts in production builds.
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=10000

WORKDIR /app

# Install the Linux system libraries required by Chromium in headless mode.
# We intentionally avoid Playwright's `--with-deps` path because we are providing the OS dependencies ourselves.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libx11-6 \
    libxi6 \
    libxext6 \
    libxshmfence1 \
    libgtk-3-0 \
    fonts-liberation \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies separately from browser installation for a cleaner, reproducible image build.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Install the Chromium browser binary without Playwright's apt-based dependency bootstrap.
# This keeps the setup compatible with the manually provisioned Debian bookworm libraries above.
RUN python -m playwright install chromium

# Copy the application source after the dependency and browser steps are complete.
COPY . .

# Document the default HTTP port; runtime PORT controls the listener.
EXPOSE 10000

# Start the API with Uvicorn in production mode.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port \"${PORT:-10000}\" --no-access-log"]
