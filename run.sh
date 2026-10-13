#!/bin/bash

echo "=== Starting BSF Farm Application ==="

export PATH="/home/runner/workspace/.pythonlibs/bin:$PATH"
export PYTHONPATH="/home/runner/workspace"

# Kill any lingering gunicorn processes that might hold port 5000
pkill -f "gunicorn.*backend" 2>/dev/null || true
sleep 1

# Initialize database schema if needed
echo "Initializing database schema..."
python -m backend.init_db || echo "Warning: Database initialization had errors (may already be initialized)"

# Start Flask application with Gunicorn (production server)
echo "Starting Flask application with Gunicorn..."
exec .pythonlibs/bin/gunicorn --bind 0.0.0.0:5000 --reuse-port --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile - backend.app:app
