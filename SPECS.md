# Especificações Técnicas - Sistema P2P com Algoritmo Bully

## 1. Descrição Geral
O sistema é um cluster distribuído composto exclusivamente por **WorkerNodes**. Não há uma autoridade central fixa (MasterNode). A coordenação é feita através de um Leader eleito dinamicamente.

### Objetivos Principais:
- Autogerenciamento (Self-healing): Eleição automática em caso de falha.
- Descentralização: Cada nó possui a mesma lógica e pode se tornar Leader.
- Sincronização: Manutenção de estado consistente sobre quem é o coordenador atual.

---

## 2. Algoritmo de Eleição Bully

### 2.1. Princípios de Funcionamento
- **ID Único**: Cada nó gera um ID numérico derivado de seu UUID.
- **Hierarquia**: Nós com IDs maiores têm prioridade sobre nós com IDs menores.
- **Gatilhos**: A eleição inicia no boot, ao detectar falha do Leader, ou quando um novo nó entra na rede.

### 2.2. Fases da Eleição
1.  **ELECTION**: Um nó envia mensagens para todos os peers com ID superior ao seu.
2.  **OK (Resposta)**: Se um nó recebe um ELECTION e possui ID maior, ele responde OK e inicia sua própria eleição.
3.  **COORDINATOR**: Se um nó não recebe OKs de nenhum superior após um timeout, ele se declara Leader e envia um broadcast de COORDINATOR para todos os nós.

---

## 3. Arquitetura do WorkerNode

### 3.1. Atributos do Nó
- `worker_uuid`: String identificadora única (8 caracteres hex).
- `worker_id`: Valor inteiro para comparações do algoritmo Bully.
- `state`: Estado atual (INITIALIZING, DISCOVERING, WAITING, FOLLOWING, ELECTING, LEADING).
- `peers`: Dicionário de nós conhecidos na rede.
- `current_leader`: UUID do nó que está coordenando o cluster.

### 3.2. Mecanismos de Rede
- **UDP (Porta 5002)**: Utilizado para Descoberta (Discovery), Heartbeats e anúncios de COORDINATOR.
- **TCP (Portas 5003+)**: Utilizado para mensagens ponto-a-ponto de ELECTION e execução de tarefas.

---

## 4. Protocolo de Mensagens

| Mensagem | Canal | Descrição |
| :--- | :--- | :--- |
| `DISCOVERY` | UDP Broadcast | Solicita presença de outros nós. |
| `DISCOVERY_OK` | UDP Unicast | Responde à descoberta com dados do nó. |
| `ELECTION` | TCP | Notifica peers superiores sobre início de eleição. |
| `ELECTION_OK` | TCP | Confirma recebimento e assume a eleição. |
| `COORDINATOR` | UDP Broadcast | Anuncia vitória na eleição e assume liderança. |
| `HEARTBEAT` | UDP Broadcast | Enviado pelo Leader para confirmar vitalidade. |
| `HEARTBEAT_OK` | UDP Unicast | Enviado pelos Workers para o Leader. |

---

## 5. Configurações Padrão
- `HEARTBEAT_INTERVAL`: 5 segundos.
- `HEARTBEAT_TIMEOUT`: 3 segundos.
- `MAX_FAILURES`: 3 falhas consecutivas antes de declarar o Leader inativo.
- `ELECTION_TIMEOUT`: 2 segundos para aguardar respostas TCP.
- `ELECTION_COOLDOWN`: 5 segundos entre tentativas de eleição.
