import os
from pathlib import Path

DATA_DIR=Path(os.getenv('DATA_DIR','data'))
DEFAULT_YEAR=int(os.getenv('BASELINE_YEAR','2025'))

def offline_mode():
    return os.getenv('DEMO_OFFLINE_MODE','').lower() in ('1','true','yes') or (DATA_DIR/'offline.flag').exists()
