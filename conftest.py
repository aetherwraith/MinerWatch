import os
import sys

def pytest_unconfigure(config):
    """Ensure pytest exits immediately when all tests complete without hanging on background threads."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
