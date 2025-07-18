#!/bin/bash

# Script to test startup timing for different Whisper models

echo "Testing startup timing for different Whisper models..."
echo "================================================"

models=("tiny" "base" "small" "medium" "large")

for model in "${models[@]}"; do
    echo ""
    echo "Testing model: $model"
    echo "------------------------"
    
    # Run the profiling script with a short duration
    uv run python profile_startup.py --model "$model" --run-duration 1 2>&1 | grep -E "\[PROFILE\].*TOTAL STARTUP TIME|Whisper model.*loading took|faster_whisper import completed"
    
    echo ""
done

echo ""
echo "================================================"
echo "Startup timing test complete!"