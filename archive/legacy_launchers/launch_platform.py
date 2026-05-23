"""Launch the 6th Degree Engineering Company Platform (Streamlit)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Log resolved runtime config so the operator sees which DB will be used.
# (A1 verification — confirms migration off OneDrive worked.)
from config import (
    AUTH_CONFIG_PATH,
    DB_BACKEND,
    DB_PATH,
    LEGACY_DB_PATH,
)

print("=" * 70)
print("6th Degree Engineering — Company Platform")
print("=" * 70)
print(f"  DB_BACKEND        = {DB_BACKEND}")
print(f"  DB_PATH           = {DB_PATH}")
print(f"  DB exists?        = {DB_PATH.exists()}")
print(f"  Legacy DB (info)  = {LEGACY_DB_PATH}")
print(f"  Legacy exists?    = {LEGACY_DB_PATH.exists()}  "
      f"(unused once new DB exists)")
print(f"  AUTH_CONFIG_PATH  = {AUTH_CONFIG_PATH}")
print(f"  AUTH exists?      = {AUTH_CONFIG_PATH.exists()}")
print("=" * 70)

if not AUTH_CONFIG_PATH.exists():
    print(
        f"ERROR: auth_config.yaml not found at {AUTH_CONFIG_PATH}.\n"
        f"Copy auth_config.example.yaml to that path, then edit it to add "
        f"a bcrypt-hashed password for the 'admin' user.\n"
        f"  python -c \"import bcrypt; "
        f"print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt(rounds=12)).decode())\""
    )
    sys.exit(1)

app = ROOT / "streamlit_app" / "Home.py"

subprocess.run(
    [
        sys.executable, "-m", "streamlit", "run", str(app),
        "--server.port", "8502",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
)
