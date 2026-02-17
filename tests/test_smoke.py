"""Smoke test — validates that the package installs and imports correctly."""

import neuroweave


def test_version():
    assert neuroweave.__version__ == "0.1.0"


def test_main_runs_without_error():
    from neuroweave.main import main

    # main() should complete without raising — it loads config + logging
    main()
