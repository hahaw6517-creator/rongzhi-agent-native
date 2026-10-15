"""Run the independent website with: python web_app.py."""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from finbridge.web_api import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")), server_header=False)
