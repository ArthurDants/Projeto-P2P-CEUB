# [Feature Name] Implementation Plan

> I'm using the writing-plans skill to create the implementation plan.

**Goal:** Implement tarefas 01, 02, 03 de forma incremental e sem gerar regressões.

**Architecture:** Abordagem não-invasiva: criar novos módulos quando possível e integrar com pontos de extensão existentes.

**Tech Stack:** Python (repositório atual), pytest para testes, padrão de commits git.

---

### Task 01: Implementação mínima (module novo)

**Files:**
- Create: `src/tasks/task01.py`
- Create tests: `tests/tasks/test_task01.py`

- [ ] **Step 1: Write the failing test**

tests/tasks/test_task01.py
```python
def test_task01_basic():
    from src.tasks.task01 import process
    assert process(2) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/tasks/test_task01.py::test_task01_basic -q
```

- [ ] **Step 3: Write minimal implementation**

src/tasks/task01.py
```python
def process(x: int) -> int:
    # implementação mínima, isolada
    return x * 2
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/tasks/test_task01.py::test_task01_basic -q
```

- [ ] **Step 5: Commit**

```bash
git add src/tasks/task01.py tests/tasks/test_task01.py
git commit -m "feat(task01): add minimal process and tests"
```

### Task 02: Adição de integração leve

**Files:**
- Create: `src/tasks/task02.py`
- Modify (optional): integrate with `src/tasks/task01.py` via import
- Create tests: `tests/tasks/test_task02.py`

- [ ] **Step 1: Write failing tests**

tests/tasks/test_task02.py
```python
def test_task02_integration():
    from src.tasks.task02 import combined
    assert combined(3) == 3 + 6
```

- [ ] **Step 2: Run test -> expect fail**

- [ ] **Step 3: Implement minimal code**

src/tasks/task02.py
```python
from src.tasks.task01 import process

def combined(x: int) -> int:
    return x + process(x)
```

- [ ] **Step 4: Run tests and commit**

### Task 03: Testes de regressão e E2E leve

**Files:**
- Create: `tests/e2e/test_e2e_basic.py`

- [ ] **Step 1: Write E2E test**

tests/e2e/test_e2e_basic.py
```python
def test_e2e_flow():
    from src.tasks.task01 import process
    from src.tasks.task02 import combined
    assert combined(4) == 4 + process(4)
```

- [ ] **Step 2: Run full test suite**

Run:
```bash
pytest -q
```

- [ ] **Step 3: If all tests pass, open PR / commit & push**

---

Execution choices: Subagent-driven (recommended) or Inline (executing-plans). Indicar preferência.
