import socket
import json
import time
import threading
import uuid
import sys
import random

# ═══════════════════════════════════════════════════════════════
# CONFIGURAÇÕES (Ajustáveis conforme seção 7 dos Specs)
# ═══════════════════════════════════════════════════════════════
HEARTBEAT_INTERVAL    = 30              # Reduzido para testes mais rápidos (original era 30)
HEARTBEAT_TIMEOUT     = 3              # Segundos para esperar resposta
MAX_FAILURES          = 3              # Falhas antes de iniciar eleição
ELECTION_TIMEOUT      = 2              # Segundos para aguardar resposta de eleição
ELECTION_COOLDOWN     = 5              # Mínimo de segundos entre eleições
ELECTION_UDP_PORT     = 5002           # Porta UDP para descoberta e broadcast
MY_ELECTION_TCP       = 5003           # Porta TCP para comunicação P2P
BROADCAST_ADDR        = "255.255.255.255"

class WorkerNode:
    def __init__(self, port=MY_ELECTION_TCP):
        self.worker_uuid = str(uuid.uuid4())[:8].upper()
        # O ID de eleição deve ser comparável. Usamos um valor numérico do UUID.
        self.worker_id = int(self.worker_uuid, 16)
        self.start_timestamp = time.time()  # MÉTODO DE DESEMPATE
        self.tcp_port = port
        
        self.running = True
        self.current_leader = None
        self.leader_timestamp = 0
        self.heartbeat_failures = 0
        self.peers = {}  # {uuid: {"id": int, "ip": str, "port": int}}
        
        # Estados: INITIALIZING, DISCOVERING, WAITING, FOLLOWING, ELECTING, LEADING
        self.state = "INITIALIZING"
        self.last_election_time = 0
        
        # Locks para thread-safety
        self.lock = threading.Lock()
        self.peers_lock = threading.Lock()
        
        # Sockets
        self.udp_sock = None
        self.tcp_sock = None

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [{self.state}] {message}")

    # ───────────────────────────────────────────────────────────
    # COMUNICAÇÃO BASE
    # ───────────────────────────────────────────────────────────

    def _setup_sockets(self):
        # UDP para Discovery e Broadcast de Eleição
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.udp_sock.bind(('', ELECTION_UDP_PORT))
        
        # TCP para comunicações P2P (Election OK, Tasks)
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.tcp_sock.bind(('0.0.0.0', self.tcp_port))
            self.tcp_sock.listen(5)
        except Exception as e:
            self.log(f"Erro ao bind TCP na porta {self.tcp_port}: {e}")
            sys.exit(1)

    def _send_udp(self, data, addr=BROADCAST_ADDR, port=ELECTION_UDP_PORT):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(json.dumps(data).encode(), (addr, port))
            sock.close()
        except Exception as e:
            self.log(f"Erro no envio UDP: {e}")

    def _send_tcp(self, ip, port, data):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(ELECTION_TIMEOUT)
                s.connect((ip, port))
                s.sendall(json.dumps(data).encode())
                return True
        except:
            return False

    # ───────────────────────────────────────────────────────────
    # DESCOBERTA (Seção 3.2.2)
    # ───────────────────────────────────────────────────────────

    def discovery_broadcast(self):
        self.state = "DISCOVERING"
        msg = {
            "TASK": "DISCOVERY",
            "WORKER_UUID": self.worker_uuid,
            "WORKER_ID": self.worker_id,
            "START_TIMESTAMP": self.start_timestamp,
            "LISTEN_PORT": self.tcp_port
        }
        self.log(f"Enviando DISCOVERY (ID: {self.worker_id}, Time: {int(self.start_timestamp)})")
        self._send_udp(msg)

    def _handle_discovery(self, msg, addr):
        peer_uuid = msg["WORKER_UUID"]
        if peer_uuid == self.worker_uuid: return
        
        peer_ip = addr[0]
        peer_port = msg["LISTEN_PORT"]
        peer_id = msg["WORKER_ID"]
        peer_ts = msg.get("START_TIMESTAMP", time.time())
        
        with self.peers_lock:
            self.peers[peer_uuid] = {
                "id": peer_id, 
                "ip": peer_ip, 
                "port": peer_port,
                "start_timestamp": peer_ts
            }
        
        self.log(f"Novo peer: {peer_uuid} (ID: {peer_id})")
        
        # Responde com DISCOVERY_OK
        reply = {
            "TASK": "DISCOVERY_OK",
            "WORKER_UUID": self.worker_uuid,
            "WORKER_ID": self.worker_id,
            "START_TIMESTAMP": self.start_timestamp,
            "LISTEN_PORT": self.tcp_port
        }
        self._send_udp(reply, addr=peer_ip)

    # ───────────────────────────────────────────────────────────
    # ALGORITMO BULLY (Seção 2)
    # ───────────────────────────────────────────────────────────

    def start_election(self):
        with self.lock:
            if time.time() - self.last_election_time < ELECTION_COOLDOWN:
                return
            self.state = "ELECTING"
            self.last_election_time = time.time()
        
        self.log("Iniciando Eleição Bully...")
        
        higher_peers = []
        with self.peers_lock:
            for uuid, info in self.peers.items():
                # LÓGICA DE COMPARAÇÃO COM DESEMPATE:
                # 1. ID maior vence.
                # 2. Se ID igual, o Timestamp menor (mais antigo) vence.
                is_higher = info["id"] > self.worker_id or \
                           (info["id"] == self.worker_id and info["start_timestamp"] < self.start_timestamp)
                
                if is_higher:
                    higher_peers.append(info)
        
        if not higher_peers:
            self.become_leader()
            return

        # Fase 1: Envia ELECTION para quem tem ID maior
        msg = {
            "TASK": "ELECTION",
            "WORKER_UUID": self.worker_uuid,
            "TIMESTAMP": time.time()
        }
        
        received_ok = False
        for peer in higher_peers:
            if self._send_tcp(peer["ip"], peer["port"], msg):
                received_ok = True
        
        if not received_ok:
            # Fase 3: Ninguém respondeu, eu sou o Leader
            self.become_leader()
        else:
            # Alguém com ID maior assumiu
            self.state = "WAITING"
            threading.Timer(ELECTION_TIMEOUT + 1, self._check_if_leader_elected).start()

    def _check_if_leader_elected(self):
        if self.state == "WAITING":
            self.log("Timeout aguardando COORDINATOR. Reiniciando eleição...")
            self.start_election()

    def become_leader(self):
        with self.lock:
            self.state = "LEADING"
            self.current_leader = self.worker_uuid
            self.heartbeat_failures = 0
        
        self.log("★ ELEITO LEADER ★")
        
        # Fase 3: Anúncio do Leader
        msg = {
            "TASK": "COORDINATOR",
            "LEADER_UUID": self.worker_uuid,
            "TIMESTAMP": time.time()
        }
        self._send_udp(msg)

    def _handle_coordinator(self, msg):
        leader_uuid = msg["LEADER_UUID"]
        with self.lock:
            self.current_leader = leader_uuid
            self.leader_timestamp = msg["TIMESTAMP"]
            self.heartbeat_failures = 0
            if leader_uuid != self.worker_uuid:
                self.state = "FOLLOWING"
        self.log(f"Reconhecido novo Leader: {leader_uuid}")

    # ───────────────────────────────────────────────────────────
    # HEARTBEAT (Seção 3.2.1)
    # ───────────────────────────────────────────────────────────

    def heartbeat_loop(self):
        while self.running:
            time.sleep(HEARTBEAT_INTERVAL)
            if self.state == "LEADING":
                msg = {"TASK": "HEARTBEAT", "LEADER_UUID": self.worker_uuid, "TIMESTAMP": time.time()}
                self._send_udp(msg)
            
    def _monitor_leader_alive(self):
        while self.running:
            time.sleep(1)
            if self.state in ["FOLLOWING", "WAITING"]:
                with self.lock:
                    self.heartbeat_failures += 1
                    if self.heartbeat_failures >= (HEARTBEAT_TIMEOUT * MAX_FAILURES):
                        self.log(f"Leader {self.current_leader} inativo. Iniciando eleição.")
                        self.current_leader = None
                        self.start_election()

    # ───────────────────────────────────────────────────────────
    # LISTENERS
    # ───────────────────────────────────────────────────────────

    def _udp_listener(self):
        while self.running:
            try:
                data, addr = self.udp_sock.recvfrom(4096)
                msg = json.loads(data.decode())
                task = msg.get("TASK")
                
                if task == "DISCOVERY":
                    self._handle_discovery(msg, addr)
                elif task == "DISCOVERY_OK":
                    peer_uuid = msg["WORKER_UUID"]
                    with self.peers_lock:
                        self.peers[peer_uuid] = {"id": msg["WORKER_ID"], "ip": addr[0], "port": msg["LISTEN_PORT"]}
                    self.log(f"Peer confirmado: {peer_uuid}")
                elif task == "COORDINATOR":
                    self._handle_coordinator(msg)
                elif task == "HEARTBEAT":
                    if msg["LEADER_UUID"] == self.current_leader:
                        with self.lock:
                            self.heartbeat_failures = 0
                        # Responde ao Leader (HEARTBEAT_OK)
                        reply = {"TASK": "HEARTBEAT_OK", "WORKER_UUID": self.worker_uuid}
                        # Como o leader envia por UDP, podemos responder por UDP para o endereço de origem
                        self._send_udp(reply, addr=addr[0])
                elif task == "HEARTBEAT_OK":
                    if self.state == "LEADING":
                        self.log(f"Heartbeat OK recebido de {msg['WORKER_UUID']}")
            except:
                continue

    def _tcp_listener(self):
        while self.running:
            try:
                conn, addr = self.tcp_sock.accept()
                threading.Thread(target=self._handle_tcp_conn, args=(conn, addr), daemon=True).start()
            except:
                break

    def _handle_tcp_conn(self, conn, addr):
        try:
            data = conn.recv(4096)
            if not data: return
            msg = json.loads(data.decode())
            task = msg.get("TASK")
            
            if task == "ELECTION":
                self.log(f"Recebido ELECTION de {msg['WORKER_UUID']}")
                reply = {"TASK": "ELECTION_OK", "WORKER_UUID": self.worker_uuid}
                conn.sendall(json.dumps(reply).encode())
                threading.Thread(target=self.start_election, daemon=True).start()
            elif task == "TASK_EXEC":
                self.log(f"Processando tarefa: {msg.get('DATA')}")
        except:
            pass
        finally:
            conn.close()

    def _task_orchestrator_loop(self):
        while self.running:
            time.sleep(10)
            if self.state == "LEADING":
                with self.peers_lock:
                    if not self.peers: continue
                    target = random.choice(list(self.peers.values()))
                
                task_msg = {"TASK": "TASK_EXEC", "DATA": f"Query_{random.randint(100,999)}"}
                self._send_tcp(target["ip"], target["port"], task_msg)

    def start(self):
        self._setup_sockets()
        threading.Thread(target=self._udp_listener, daemon=True).start()
        threading.Thread(target=self._tcp_listener, daemon=True).start()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._monitor_leader_alive, daemon=True).start()
        threading.Thread(target=self._task_orchestrator_loop, daemon=True).start()
        
        self.discovery_broadcast()
        time.sleep(1)
        self.start_election()
        
        self.log(f"Worker {self.worker_uuid} (ID: {self.worker_id}) rodando na porta {self.tcp_port}")
        try:
            while self.running: time.sleep(1)
        except KeyboardInterrupt:
            self.running = False

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else MY_ELECTION_TCP
    WorkerNode(port=port).start()
