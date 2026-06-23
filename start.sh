#!/bin/bash
# start.sh — run both backend and frontend

set -e

# Start backend
echo "→ Starting FastAPI backend on :8000..."
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!
cd ..

# Start frontend
echo "→ Starting Next.js frontend on :3000..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "=== ShopWave AI Refund Agent is running! ==="
echo ""
echo "  Customer Chat:  http://localhost:3000"
echo "  Admin Dashboard: http://localhost:3000/admin"
echo "  API Docs:       http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services."

# Handle shutdown
trap "echo ''; echo 'Stopping...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM

wait
