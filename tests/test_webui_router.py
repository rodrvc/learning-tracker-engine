"""Runs webui/js/'s Node unit tests as part of the pytest suite.

router.js, api.js's request() and format.js are kept DOM-free specifically so
they can be unit tested without a browser (ACU-265). Node's built-in test
runner needs no extra dependency; CI declares the Node dependency itself via
``actions/setup-node`` (see .github/workflows/test-suite.yml). This fails
loudly rather than skipping when node is missing, matching the project's
"a skip is a configuration failure" stance for the Postgres suite.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBUI_TEST_DIR = REPO_ROOT / "tests" / "webui"


@pytest.mark.spec
def test_webui_js_unit_tests_pass():
    if shutil.which("node") is None:
        pytest.fail("node is required to run webui/js/'s unit tests")
    result = subprocess.run(
        ["node", "--test", str(WEBUI_TEST_DIR)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
