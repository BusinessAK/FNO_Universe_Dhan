import time
from vanguard.serve.api import Bridge

if __name__ == '__main__':
    b = Bridge()
    b.start()
    while True:
        time.sleep(1)
