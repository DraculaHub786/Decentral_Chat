"""Convenience entrypoint: python run.py from backend/."""
import sys
from pathlib import Path

# Ensure backend/ is importable (for `from app...`)
BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import main

if __name__ == '__main__':
    main()
