#!/bin/bash

# Script to install Spendy project dependencies
# Fixes SSL certificate issues on macOS

echo "🚀 Installing dependencies for Spendy"
echo "====================================="
echo ""

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Install Python 3.10+"
    exit 1
fi

echo "✅ Python found: $(python3 --version)"
echo ""

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi
echo ""

# Activate virtual environment
echo "🔄 Activating virtual environment..."
source venv/bin/activate

# Update pip
echo "⬆️  Updating pip..."
pip install --upgrade pip --quiet

# Install dependencies
echo "📥 Installing dependencies..."
echo "   (this may take a few minutes)"
echo ""

# Check for SSL issues
if pip install -r requirements.txt 2>&1 | grep -q "SSLError\|certificate"; then
    echo "⚠️  SSL certificate issue detected"
    echo "🔧 Reinstalling with trusted hosts..."
    pip install --trusted-host pypi.org \
                --trusted-host pypi.python.org \
                --trusted-host files.pythonhosted.org \
                -r requirements.txt
else
    echo "✅ Installation completed without issues"
fi

# Verify installation
echo ""
echo "🧪 Verifying installation..."
if python -c "import fastapi; import uvicorn; import sqlalchemy" 2>/dev/null; then
    echo "✅ All dependencies installed successfully!"
else
    echo "❌ Error verifying dependencies"
    exit 1
fi

echo ""
echo "====================================="
echo "🎉 Installation complete!"
echo ""
echo "To run the application:"
echo "  source venv/bin/activate"
echo "  python run.py"
echo ""
echo "Or simply:"
echo "  ./start.sh"
echo "====================================="
