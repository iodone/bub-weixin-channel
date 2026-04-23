FROM python:3.12-slim

# git: required for weixin-agent-sdk install from GitHub
# boxsh: sandboxed shell for agent command execution
RUN apt-get update && apt-get install -y --no-install-recommends git curl libncurses6 fuse-overlayfs && rm -rf /var/lib/apt/lists/* \
    && echo "user_allow_other" >> /etc/fuse.conf

# Install boxsh (sandboxed shell for agent command execution)
ARG BOXSH_VERSION=v2.1.0
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then ARCH="x64"; elif [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi && \
    curl -fsSL "https://github.com/xicilion/boxsh/releases/download/${BOXSH_VERSION}/boxsh-${BOXSH_VERSION}-linux-${ARCH}" \
      -o /usr/local/bin/boxsh && \
    chmod +x /usr/local/bin/boxsh

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install project
COPY src/ src/
COPY README.md ./
RUN uv sync --frozen --no-dev

# Install bub plugins
RUN uv run bub install bub-schedule@main

# Copy entrypoint script (unified entry for service and debugging)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Volumes:
#   /workspace                       - agent workspace (read-only base, COW via boxsh)
#   /boxsh                           - COW write layer for /workspace (persists agent writes)
#   /root/.agents/skills             - bub skills directory (read-only in boxsh)
#   /root/.openclaw/openclaw-weixin  - weixin credentials (read-only in boxsh)
#   /root/.bub                       - bub home (read-write in boxsh for tapes, config)
VOLUME /workspace
VOLUME /boxsh
VOLUME /root/.agents/skills
VOLUME /root/.openclaw/openclaw-weixin
VOLUME /root/.bub

ENTRYPOINT ["/entrypoint.sh"]
CMD []
