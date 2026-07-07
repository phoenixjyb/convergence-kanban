#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# ConvergenceKanban — one-shot installer.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/phoenixjyb/convergence-kanban/main/install.sh | bash
#   or, in a cloned checkout:
#   ./install.sh
#
# What it does:
#   1. Verifies prerequisites (docker, git)
#   2. Clones the repo (skipped if you're already in a checkout)
#   3. Generates .env from .env.example with sensible defaults
#   4. Builds the docker image
#   5. Starts the kanban service
#   6. Prints the URL + next steps
# ─────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_URL="${CONVERGENCE_KANBAN_REPO:-https://github.com/phoenixjyb/convergence-kanban.git}"
INSTALL_DIR="${CONVERGENCE_KANBAN_INSTALL_DIR:-convergence-kanban}"
DEFAULT_PORT="${CONVERGENCE_KANBAN_PORT:-8666}"

# Colors
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[0;33m'
BLU='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLU}==>${NC} $1"; }
warn()  { echo -e "${YLW}!! ${NC} $1"; }
error() { echo -e "${RED}xx${NC} $1" >&2; exit 1; }
ok()    { echo -e "${GRN}OK${NC} $1"; }

# 1. Prerequisites ────────────────────────────────────────────────────────

info "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || error "Docker not found. Install Docker first: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || error "'docker compose' not available. Install the docker-compose plugin."
command -v git >/dev/null 2>&1 || warn "git not found — you'll need it to clone the repo manually."
ok "Prerequisites look good."

# 2. Clone repo if needed ─────────────────────────────────────────────────

if [[ -f "app.py" && -f "Dockerfile" ]]; then
    info "Detected an existing checkout — installing in place."
    INSTALL_DIR="$(pwd)"
else
    if [[ -d "$INSTALL_DIR" ]]; then
        info "Directory '$INSTALL_DIR' already exists — cd-ing in."
    else
        info "Cloning $REPO_URL into '$INSTALL_DIR'..."
        git clone "$REPO_URL" "$INSTALL_DIR" || error "git clone failed"
    fi
    cd "$INSTALL_DIR"
fi

# 3. Generate .env ────────────────────────────────────────────────────────

if [[ ! -f .env ]]; then
    info "Creating .env from .env.example..."
    cp .env.example .env

    # Set the port via env var if user supplied it
    if [[ "$DEFAULT_PORT" != "8666" ]]; then
        sed -i.bak "s|^PORT=.*|PORT=$DEFAULT_PORT|" .env && rm -f .env.bak
        ok "Port set to $DEFAULT_PORT."
    fi
    ok ".env created. Feishu integration is OFF by default — edit .env to enable."
else
    info ".env already exists — leaving it alone."
fi

# 4. Build + start ────────────────────────────────────────────────────────

info "Building Docker image (first time may take 1-2 min)..."
docker compose build kanban || error "docker build failed"

info "Starting kanban service..."
docker compose up -d kanban || error "docker compose up failed"

# 5. Wait for health ──────────────────────────────────────────────────────

info "Waiting for kanban to come up..."
PORT=$(grep -E "^PORT=" .env | cut -d= -f2 | tr -d ' ')
PORT="${PORT:-$DEFAULT_PORT}"
for i in {1..20}; do
    if curl -fsS "http://localhost:$PORT/" >/dev/null 2>&1; then
        ok "Kanban is responding on port $PORT."
        break
    fi
    sleep 1
    [[ $i -eq 20 ]] && warn "Service didn't respond in 20s — check 'docker compose logs kanban'."
done

# 6. Done ─────────────────────────────────────────────────────────────────

cat <<EOF

${GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}
${GRN}ConvergenceKanban is up.${NC}

  Web UI:        http://localhost:$PORT
  API base:      http://localhost:$PORT/api
  Bug tracker:   http://localhost:$PORT/bugs
  Analytics:     http://localhost:$PORT/analytics
  Agent guide:   http://localhost:$PORT/api/agent-guide

Next steps:
  - Edit .env to enable Feishu integration (optional)
  - With Feishu: docker compose --profile feishu up -d
  - Register your first user via the UI ('login' button)
  - For AI agents: drop a one-liner in their CLAUDE.md / AGENTS.md:
      ConvergenceKanban API guide: http://YOUR_HOST:$PORT/api/agent-guide

Docs:
  - Full setup guide:  docs/SETUP.md
  - Agent integration: docs/AGENT_INSTRUCTIONS.md
  - Architecture:      docs/AGENT_ARCHITECTURE_zh.md (Chinese)

Manage with:
  docker compose logs -f kanban
  docker compose down                # stop
  docker compose up -d               # restart
${GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}
EOF
