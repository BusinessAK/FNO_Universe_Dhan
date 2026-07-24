import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vanguard.serve.api import Bridge

if __name__ == '__main__':
    b = Bridge()
    b.start()
    while True:
        time.sleep(1)
