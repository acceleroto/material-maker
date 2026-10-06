#!/bin/zsh
# usage: export.sh <abs ptex> <abs outdir>
P="$1"; O="$2"; mkdir -p "$O"; rm -f "$O/DONE"
S=$(date +%s.%N 2>/dev/null || date +%s)
"/Applications/Material Maker.app/Contents/MacOS/Material Maker" --export-material --target "Unity/URP" -o "$O" "$P" > "$O/log.txt" 2>&1
E=$(date +%s)
echo "exit=$? start=$S end=$E" > "$O/DONE"
