"""Qt UI tests run headless on every platform."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
