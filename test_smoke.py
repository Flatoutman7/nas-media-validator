def test_smoke_imports():
    # Keep this test lightweight so CI doesn't require the GUI stack.
    import hardware
    import scan_history
    import scan_metadata_cache
    import main

    assert callable(main.run_scan)

