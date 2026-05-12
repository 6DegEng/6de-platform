"""Launch the 6th Degree Engineering Company Platform (Streamlit)."""

import subprocess
import sys
from pathlib import Path

app = Path(__file__).parent / "streamlit_app" / "Home.py"

subprocess.run(
    [
        sys.executable, "-m", "streamlit", "run", str(app),
        "--server.port", "8502",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
)
