# Session 0.3 prototypes (throwaway; superseded by `mmx` in Phase 1)

- `export.sh <abs ptex> <abs outdir>`: Unity/URP export, log to `outdir/log.txt`, writes `outdir/DONE`
  when finished. Launch it with `run_in_terminal`, then poll for `DONE` from Bash.
- `g.py`: tiny `.ptex` edit helpers (`Graph.set/add/wire/save`, `G()` gradients, `C()` colours).
- `sheet.py <outdir>`: contact sheet with a crude Lambert-lit preview (1×, 2×2 tiled, ¼ crop) + maps.
  Needs Pillow + numpy (not installed system-wide; used a venv in the session scratchpad).
