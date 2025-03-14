#!/bin/sh
set -e

CONFIG_DIR="/app/data"

# Ensure config directory exists
mkdir -p "$CONFIG_DIR"

# Copy default config files only if the directory is empty
if [ -z "$(ls -A $CONFIG_DIR)" ]; then
    echo "No config files found in $CONFIG_DIR, copying defaults..."
    cp -r /app/defaults/* "$CONFIG_DIR/"
else
    echo "Config files already exist in $CONFIG_DIR, skipping copy."
fi

# Start the main process
exec "$@"
