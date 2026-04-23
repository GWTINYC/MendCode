import sys
from pathlib import Path

fixture_root = Path(__file__).resolve().parents[1]
if str(fixture_root) not in sys.path:
    sys.path.insert(0, str(fixture_root))

from buggy_math import add  # noqa: E402


def test_add_returns_sum():
    assert add(2, 3) == 5
