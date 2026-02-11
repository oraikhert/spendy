#!/bin/bash

# Quick start script for Spendy

# Check for virtual environment
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found"
    echo "Run first: ./install.sh"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Run application
echo "🚀 Starting Spendy..."
echo "📖 Docs: http://localhost:8000/docs"
echo "🛑 Stop: Ctrl+C"
echo ""
python run.py
