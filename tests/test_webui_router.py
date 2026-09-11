"""Runs webui/js/router.js's own unit tests as part of the pytest suite.

``router.js`` is kept free of the DOM specifically so it can be unit tested
without a browser (ACU-265's "whatever JavaScript logic is worth testing
without a browser"). Node ships a built-in test runner, so no extra
dependency is needed to exercise it - this just wires that run into the one
suite CI already runs.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTER_TEST = REPO_ROOT / "tests" / "webui" / "router.test.mjs"


@pytest.mark.spec
def test_router_js_unit_tests_pass():
    if shutil.which("node") is None:
        pytest.fail("node is required to run webui/js/router.js's unit tests")
    result = subprocess.run(
        ["node", "--test", str(ROUTER_TEST)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
