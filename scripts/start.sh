#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv/Scripts/activate"

# Activate venv if not already active
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -f "$VENV" ]; then
        echo "Activating venv..."
        source "$VENV"
    else
        echo "Error: No venv found at $VENV"
        echo "Run: python -m venv backend/.venv && backend/.venv/Scripts/pip install -r backend/requirements.txt"
        exit 1
    fi
fi

# Load .env.local
ENV_FILE="$ROOT/.env.local"
if [ -f "$ENV_FILE" ]; then
    echo "Loading $ENV_FILE..."
    set -a
    source "$ENV_FILE"
    set +a
fi

# Start backend in background
echo "Starting backend (uvicorn :8000)..."
cd "$BACKEND"
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Wait for backend to be ready
echo "Waiting for backend..."
until curl -s http://localhost:8000/health > /dev/null 2>&1; do
    sleep 1
done
echo "Backend ready."

# Start frontend (blocks until Ctrl+C)
echo "Starting frontend (vite :5173)..."
cd "$FRONTEND"
npm run dev

# Clean up backend when frontend exits
kill $BACKEND_PID 2>/dev/null
