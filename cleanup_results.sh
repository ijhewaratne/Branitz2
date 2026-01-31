#!/bin/bash

# Function to move if not the target
move_others() {
    phase=$1
    target="ST010_HEINRICH_ZILLE_STRASSE"
    
    echo "Processing $phase..."
    
    # Check if target base exists
    if [ -d "results/$phase/$target" ]; then
        echo "  Base target found: $target"
        # Move everything that is NOT the strict target
        for dir in results/$phase/*; do
            dirname=$(basename "$dir")
            if [ "$dirname" != "$target" ] && [ "$dirname" != "unnecessary" ]; then
                echo "  Moving $dirname to unnecessary/$phase"
                mv "$dir" "results/unnecessary/$phase/"
            fi
        done
    else
        echo "  Base target NOT found. Checking for partial matches..."
        # If base target doesn't exist, keep the timestamped version if it exists
        # Actually, let's keep anything containing "ST010" and move others
        
        for dir in results/$phase/*; do
            dirname=$(basename "$dir")
            
            # Skip if it's the output dir itself (shouldn't happen with glob, but good practice) or unnecessary
            if [ "$dirname" == "unnecessary" ]; then continue; fi
            if [ ! -d "$dir" ]; then continue; fi

            if [[ "$dirname" == *"$target"* ]]; then
                echo "  Keeping partial match: $dirname"
            else
                echo "  Moving $dirname to unnecessary/$phase"
                mv "$dir" "results/unnecessary/$phase/"
            fi
        done
    fi
}

move_others "cha"
move_others "dha"
move_others "decision"
move_others "economics"
move_others "report"
move_others "uhdc"

echo "Cleanup complete."
