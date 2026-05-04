# Plano de Implementação - Algoritmo Bully P2P

## 1. Cronograma e Fases

### Fase 1: Infraestrutura e Descoberta (Semanas 1-2) ✅
- [x] Implementação da classe `WorkerNode`.
- [x] Criação do sistema de sockets Híbrido (UDP/TCP).
- [x] Implementação do mecanismo de Discovery via Broadcast UDP.

### Fase 2: Lógica de Eleição (Semanas 3-4) ✅
- [x] Geração de IDs determinísticos a partir de UUIDs.
- [x] Implementação das mensagens `ELECTION` e `ELECTION_OK`.
- [x] Lógica de transição para o estado `LEADING` e envio de `COORDINATOR`.

### Fase 3: Resiliência e Heartbeat (Semanas 5-6) ✅
- [x] Implementação do loop de Heartbeat no Leader.
- [x] Monitoramento de falhas nos Followers.
- [x] Resposta de `HEARTBEAT_OK` para manter estatísticas de vitalidade.

### Fase 4: Estabilidade e Thread Safety (Semanas 7-8) ✅
- [x] Aplicação de Locks (`peers_lock`, `lock`) para evitar race conditions.
- [x] Implementação de Cooldown de eleição para evitar oscilações na rede.

### Fase 5: Validação e Testes (Semanas 9-10) ⏳
- [x] Criação do script de simulação `simulate_cluster.py`.
- [ ] Execução de testes de stress com mais de 10 nós.
- [ ] Teste de partição de rede e reconexão.

---

## 2. Milestones Principais
1.  **Cluster Discovery**: Nós conseguem se encontrar na rede local sem IP fixo.
2.  **Deterministic Leadership**: O nó com maior ID sempre assume após um timeout.
3.  **Self-Healing**: Ao derrubar o processo do Leader, o próximo nó mais potente assume em < 15 segundos.

---

## 3. Gestão de Riscos
- **Risco**: Storm de mensagens em redes grandes.
- **Mitigação**: Uso de timeouts curtos e mensagens UDP leves para heartbeats.
- **Risco**: Dois líderes (Split Brain).
- **Mitigação**: Verificação de ID no recebimento de `COORDINATOR` e reinício de eleição se houver conflito.

---

## 4. Próximos Passos
1. Realizar testes de longa duração para validar estabilidade dos locks.
2. Implementar uma camada de "Job Distribution" real sobre a estrutura de liderança.
3. Finalizar a documentação do usuário no `README.md`.
