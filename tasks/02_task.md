# Tarefa 02 — Integração leve

Objetivo: integrar `task02` com `task01` de forma não-invasiva.

Passos resumidos:
- Criar `src/tasks/task02.py` que importa `process` de `task01` e expõe `combined(x)`.
- Criar `tests/tasks/test_task02.py` com teste de integração simples.
- Rodar `pytest` e commitar.

Critério de aceitação:
- `pytest tests/tasks/test_task02.py` passa e integração é validada.
