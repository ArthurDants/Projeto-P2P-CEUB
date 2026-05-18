# Análise do `final.pdf` vs código atual

Data: 2026-05-18

Resumo rápido
- Extraído `final.pdf` (16 páginas). Texto salvo em `docs/final_text.txt`.
- Identifiquei os requisitos principais (objetivos O1..O6, Sprints 1..3) e comparei com o repositório atual.

Funcionalidades presentes (mapeamento):
- TCP framing com delimitador `\n`: implementado em [master.py] para envio/recebimento (`_send`, `_recv_line`).
- Gerador/Simulação de carga: `MasterNode._start_task_generator` em [master.py].
- Fila de tarefas e dispatch básico: `MasterNode._dispatch_task` e uso de `queue.Queue`.
- Recebimento de status/ACK básico: `MasterNode.handle_worker` recebe `STATUS` e envia `ACK`.
- Monitor de saturação: `MasterNode._monitor_saturation` imprime alerta quando `task_queue.qsize() >= THRESHOLD`.
- Mecanismos de Worker/Task locais de simulação: arquivos `src/tasks/*` e testes adicionados (tarefas 01/02/03).
- Nó Worker com descoberta e algoritmo Bully (eleições) e UDP/TCP P2P: `worker.py`.

Principais lacunas / itens faltantes (prioridade alta → baixa):

1) Worker TCP client + ciclo de vida Master↔Worker (ALTA)
   - O `Master` assume que os `Worker`s abrem uma conexão TCP e mantêm-na aberta, enviando mensagens JSON delimitadas por `\n` (heartbeat, apresentação, status). Atualmente `worker.py` implementa comunicação P2P (discovery via UDP, TCP server para peers) mas NÃO implementa o cliente TCP que conecta-se ao Master e processa comandos `TASK` / `NO_TASK` recebidos. Sem isso, o fluxo de Sprint 1/2 não está completo.

2) Protocolo consensual Master↔Master para empréstimo de Workers (ALTA)
   - `final.pdf` exige um protocolo de negociação para que um Master saturado solicite Workers a Masters vizinhos e coordene a transferência. Não há implementação explícita de negociação entre Masters nem endpoints para `REQUEST_BORROW`, `ACCEPT_BORROW`, `TRANSFER` etc.

3) Handoff de Worker (ALTA)
   - Quando um Master empresta um Worker, o Worker deve ser capaz de desconectar do Master original e conectar-se ao novo Master conforme instruções. `worker.py` não tem rota de controle para reconectar a outro Master conforme payload do Master.

4) Persistência mínima / log de tarefas (MÉDIO)
   - `MasterNode` registra em memória `completed_log` mas não persiste em disco; persistência simples (arquivo JSON/CSV) recomendada para auditoria e testes E2E.

5) Protocolo de consenso resiliente (MÉDIO)
   - Regras de timeout/retry, confirmação idempotente e tratamento de falhas durante transferência de Workers precisam ser definidas e implementadas (mensagens de compensação, rollback parcial).

6) Testes automatizados de integração e E2E (MÉDIO)
   - Há testes unitários para `src/tasks`, mas falta uma suíte E2E que simule Master + N Workers executando handshake, entrega de QUERY, processamento e ACK, além de cenários de saturação e empréstimo.

7) Documentação operacional / DoD completos (BAIXA)
   - `final.pdf` contém checklists DoD (parciais). Precisamos preenchê-los no repo (`docs/`) e versionar.

Recomendações de próxima iteração (pragmáticas)
1. Implementar o cliente TCP no `worker.py` que:
   - conecta-se ao `Master` (IP/PORT configurável), envia payloads padrão (apresentação `{"WORKER":"ALIVE","WORKER_UUID":"...","SERVER_UUID":...}`), escuta linhas JSON terminadas em `\n`, processa `TASK`/`NO_TASK`, executa trabalho (sleep/calc) e envia `STATUS` e aguarda `ACK`.

2. Implementar API simples de negociação Master↔Master (HTTP-JSON ou TCP-JSON):
   - Endpoints/msgs: `BORROW_REQUEST`, `BORROW_RESPONSE`, `TRANSFER_INSTRUCT`, `TRANSFER_ACK`.
   - Modelo de fluxo: MasterA saturado → envia `BORROW_REQUEST` com #workers/timeout → MasterB responde `ACCEPT/REJECT` → se `ACCEPT` MasterB marca Worker(s) como `emp` e envia `TRANSFER_INSTRUCT` ao Worker(s).

3. Implementar handoff no Worker: aceitar `TRANSFER_INSTRUCT` e reconectar para novo Master.

4. Adicionar testes E2E: script que sobe 1 Master + 2 Workers, gera carga para atingir threshold e valida fluxo de empréstimo (mock ou real).

5. Persistência mínima do log de tarefas no Master (`logs/tasks.log`), com rotação simples.

Proposta imediata (próximo passo) — escolha recomendada
- Prioridade: implementar o `Worker TCP client + apresentação` (item 1) — é requisito para validar todo o fluxo de Sprint 1/2 e para poder testar o protocolo de empréstimo depois.

Arquivos criados/atualizados durante análise
- `docs/final_text.txt` (texto extraído do PDF)
- `docs/final_analysis.md` (este arquivo)

Pergunta curta para avançar
- Quer que eu implemente agora o `Worker TCP client + apresentação` como primeira tarefa? (sim / não / prefiro discutir detalhes)
