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

    from nas_checker.scan.main import run_scan  # noqa: F401
    from health.hardware import recommend_scan_workers  # noqa: F401
    from health.scan_history import ScanHistory  # noqa: F401
    from health.scan_metadata_cache import ScanMetadataCache  # noqa: F401

    assert callable(run_scan)
    assert callable(recommend_scan_workers)
    assert ScanHistory is not None
    assert ScanMetadataCache is not None
