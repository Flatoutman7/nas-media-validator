def test_smoke_imports():
    # Keep this test lightweight so CI doesn't require the GUI stack.
    #
    # Pytest can run with a working directory that doesn't automatically put the
    # repo root on `sys.path`, so we force it.
    import os
    import sys

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    import hardware  # noqa: F401
    import scan_history  # noqa: F401
    import scan_metadata_cache  # noqa: F401
    import main

    assert callable(main.run_scan)
    assert callable(hardware.recommend_scan_workers)
