#!/usr/bin/env bash
# build.sh - Render build script

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Running database migrations..."
python migrate.py

echo "Build completed successfully!"
