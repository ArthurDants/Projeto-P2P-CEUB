def test_e2e_flow():
    from src.tasks.task01 import process
    from src.tasks.task02 import combined
    assert combined(4) == 4 + process(4)
