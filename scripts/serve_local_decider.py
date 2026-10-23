"""Start a local Strands Decider on this Mac (MLX), the same checkpoint as the hosted API.

One-time install (separate venv, keeps torch/mlx out of the app's venv):
    uv venv --python 3.12 .decider-venv
    uv pip install --python .decider-venv/bin/python \
        "strands-decider[mlx] @ git+https://github.com/strands-labs/strands-decider@b9fc836"
Run:  python scripts/serve_local_decider.py      (serves http://127.0.0.1:8099, no auth, localhost only)
Then: DECIDER_MODE=local in .env (DECIDER_BASE_URL=http://127.0.0.1:8099).
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
exe = ROOT / ".decider-venv" / "bin" / "strands-decider"
model = os.environ.get("LOCAL_DECIDER_MODEL", "StrandsAgents/strands-decider-2B-hobson-v19")
device = os.environ.get("LOCAL_DECIDER_DEVICE", "mlx")
if not exe.exists():
    sys.exit(__doc__)
sys.exit(subprocess.call([str(exe), "serve", model, "--device", device, "--port", "8099"]))
