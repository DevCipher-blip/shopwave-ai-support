#!/bin/bash
# setup.sh — one-time project setup

set -e
echo "=== ShopWave AI Refund Agent Setup ==="

# Backend
echo ""
echo "→ Setting up Python backend..."
cd backend

if [ ! -f .env ]; then
  cp .env.example .env
  echo "  ✓ Created backend/.env — ADD YOUR GROQ_API_KEY"
else
  echo "  ✓ backend/.env already exists"
fi

python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "  ✓ Python dependencies installed"

cd ..

# Frontend
echo ""
echo "→ Setting up Next.js frontend..."
cd frontend
npm install --silent
echo "  ✓ Node dependencies installed"

cd ..

echo ""
echo "=== Setup complete! ==="
echo ""
echo "IMPORTANT: Edit backend/.env and set GROQ_API_KEY=gsk_xxxx"
echo "Get your FREE key at: https://console.groq.com"
echo ""
echo "Then run: ./start.sh"
