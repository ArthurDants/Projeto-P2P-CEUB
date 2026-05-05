from src.tasks.task01 import process

def combined(x: int) -> int:
    """Combina o valor x com o resultado de `process(x)` de task01.

    Implementação não-invasiva que reutiliza `task01.process`.
    """
    return x + process(x)
