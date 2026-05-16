#!/bin/bash

# Copy MT5 export files from Wine WINEPREFIX to workspace
# This script should be run after MT5 backtests complete

WINEPREFIX_PATH="/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5"
MT5_COMMON_FILES="$WINEPREFIX_PATH/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files"
WORKSPACE_ROOT="/Users/niko/Documents/projects/niko-ai"

# Create timestamp for file naming
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Function to copy file if it exists
copy_if_exists() {
    local source=$1
    local dest_name=$2
    
    if [ -f "$source" ]; then
        dest="$WORKSPACE_ROOT/${dest_name}_${TIMESTAMP}.csv"
        cp "$source" "$dest"
        echo "✓ Copied: $dest_name → $(basename $dest)"
        return 0
    else
        echo "✗ Not found: $source"
        return 1
    fi
}

echo "Copying MT5 exports from Common Files..."
echo "Source: $MT5_COMMON_FILES"
echo ""

copy_if_exists "$MT5_COMMON_FILES/phantom_mt5_tester_export.csv" "phantom_mt5_tester_export"
copy_if_exists "$MT5_COMMON_FILES/phantom_mt5_export.csv" "phantom_mt5_export"

echo ""
echo "Also updating latest symlinks..."
[ -f "$WORKSPACE_ROOT/phantom_mt5_tester_export_latest.csv" ] && rm "$WORKSPACE_ROOT/phantom_mt5_tester_export_latest.csv"
[ -f "$WORKSPACE_ROOT/phantom_mt5_export_latest.csv" ] && rm "$WORKSPACE_ROOT/phantom_mt5_export_latest.csv"

if [ -f "$WORKSPACE_ROOT/phantom_mt5_tester_export_${TIMESTAMP}.csv" ]; then
    ln -s "phantom_mt5_tester_export_${TIMESTAMP}.csv" "$WORKSPACE_ROOT/phantom_mt5_tester_export_latest.csv"
    echo "✓ Updated: phantom_mt5_tester_export_latest.csv symlink"
fi

if [ -f "$WORKSPACE_ROOT/phantom_mt5_export_${TIMESTAMP}.csv" ]; then
    ln -s "phantom_mt5_export_${TIMESTAMP}.csv" "$WORKSPACE_ROOT/phantom_mt5_export_latest.csv"
    echo "✓ Updated: phantom_mt5_export_latest.csv symlink"
fi

echo ""
echo "Done! Export files are ready for analysis."
