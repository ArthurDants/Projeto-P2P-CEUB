def test_task02_integration():
    from src.tasks.task02 import combined
    assert combined(3) == 3 + 6
