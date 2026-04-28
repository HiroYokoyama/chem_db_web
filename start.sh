#!/usr/bin/env bash
set -euo pipefail

if [ ! -f "venv/bin/activate" ]; then
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

source venv/bin/activate

echo "Molibrary is starting..."
echo "Use --localhost to restrict access to this PC only."
echo
python molibrary/app.py "$@"
