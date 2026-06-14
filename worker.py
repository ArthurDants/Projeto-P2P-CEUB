import argparse
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
MASTER_HOST           = "127.0.0.1"
MASTER_PORT           = 5000
MASTER_DISCOVERY_WAIT = 5

class WorkerNode:
    def __init__(self, port=MY_ELECTION_TCP):
        self.worker_uuid = str(uuid.uuid4())[:8].upper()
        # O ID de eleição deve ser comparável. Usamos um valor numérico do UUID.
        self.worker_id = int(self.worker_uuid, 16)
        self.start_timestamp = time.time()  # MÉTODO DE DESEMPATE
        self.tcp_port = port
        self.master_host = MASTER_HOST
        self.master_port = MASTER_PORT
        self.master_discovered = False
        self.master_discovery_time = None
        # Rastrear master original para comando_release (Sprint 3)
        self.original_master_host = None
        self.original_master_port = None
        # request_id recebido em command_redirect (Sprint 3)
        self.redirect_request_id = None
        
        self.running = True
        self.current_leader = None
        self.leader_timestamp = 0
        self.heartbeat_failures = 0
        self.peers = {}  # {uuid: {"id": int, "ip": str, "port": int}}
        self.last_master_no_task = False
        # Timestamp do último heartbeat recebido do líder
        self.last_heartbeat_time = time.time()
        
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

    def _get_local_broadcast(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            parts = ip.split(".")
            if len(parts) == 4:
                parts[-1] = "255"
                return ".".join(parts)
        except Exception:
            pass
        return BROADCAST_ADDR

    def _send_udp(self, data, addr=BROADCAST_ADDR, port=ELECTION_UDP_PORT):
        message = json.dumps(data).encode()
        try:
            if self.udp_sock:
                self.udp_sock.sendto(message, (addr, port))
                local_bcast = self._get_local_broadcast()
                if local_bcast != addr:
                    try:
                        self.udp_sock.sendto(message, (local_bcast, port))
                    except Exception:
                        pass
                return

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(('', ELECTION_UDP_PORT))
            sock.sendto(message, (addr, port))
            local_bcast = self._get_local_broadcast()
            if local_bcast != addr:
                try:
                    sock.sendto(message, (local_bcast, port))
                except Exception:
                    pass
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

    def _send_tcp_with_response(self, ip, port, data, timeout=2):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((ip, port))
                s.sendall((json.dumps(data) + "\n").encode())
                buf = b""
                while b"\n" not in buf:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                if b"\n" in buf:
                    line, _ = buf.split(b"\n", 1)
                    try:
                        return json.loads(line.decode())
                    except Exception:
                        return None
                return None
        except Exception:
            return None

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

    def _handle_master_announce(self, msg, addr):
        host = msg.get("HOST") or addr[0]
        port = msg.get("PORT") or MASTER_PORT
        try:
            port = int(port)
        except Exception:
            port = MASTER_PORT
        if host == "0.0.0.0":
            host = addr[0]
        self.master_host = host
        self.master_port = port
        self.master_discovered = True
        self.log(f"Master descoberto em {host}:{port}")

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
                is_higher = info["id"] > self.worker_id or \
                           (info["id"] == self.worker_id and info["start_timestamp"] < self.start_timestamp)
                if is_higher:
                    higher_peers.append(info)
        
        if not higher_peers:
            self.become_leader()
            return

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
            self.become_leader()
        else:
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
            # Resetar timestamp do último heartbeat ao reconhecer novo líder
            self.last_heartbeat_time = time.time()
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
                    # Se não houver líder conhecido, nada a checar
                    if not self.current_leader:
                        continue
                    # Tempo desde o último heartbeat recebido
                    elapsed = time.time() - getattr(self, 'last_heartbeat_time', 0)
                    # Permitir um período tolerante baseado no intervalo de heartbeat + margem
                    threshold = HEARTBEAT_INTERVAL + (HEARTBEAT_TIMEOUT * MAX_FAILURES)
                    if elapsed > threshold:
                        self.log(f"Leader {self.current_leader} inativo (timeout {int(elapsed)}s). Iniciando eleição.")
                        self.current_leader = None
                        threading.Thread(target=self.start_election, daemon=True).start()

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
                    peer_ts = msg.get("START_TIMESTAMP", time.time())
                    with self.peers_lock:
                        self.peers[peer_uuid] = {"id": msg["WORKER_ID"], "ip": addr[0], "port": msg["LISTEN_PORT"], "start_timestamp": peer_ts}
                    self.log(f"Peer confirmado: {peer_uuid}")
                elif task == "COORDINATOR":
                    self._handle_coordinator(msg)
                elif task == "MASTER_ANNOUNCE":
                    self._handle_master_announce(msg, addr)
                elif task == "HEARTBEAT":
                    if msg["LEADER_UUID"] == self.current_leader:
                        with self.lock:
                            # Atualiza timestamp do último heartbeat recebido
                            self.last_heartbeat_time = time.time()
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
            elif task == "TASK_EXEC" or task == "QUERY":
                # Normalize task payload: accept TASK_EXEC with DATA or QUERY with USER
                user = msg.get("USER") or msg.get("DATA") or "<unknown>"
                self.log(f"Processando tarefa: {user}")
                # Simula processamento curto
                try:
                    time.sleep(random.uniform(0.1, 0.6))
                except Exception:
                    pass
                # Responder com status semelhante ao Master
                status = {"STATUS": "OK", "TASK": "QUERY", "WORKER_UUID": self.worker_uuid}
                try:
                    conn.sendall((json.dumps(status) + "\n").encode())
                except Exception:
                    pass
        except:
            pass
        finally:
            conn.close()

    def _task_orchestrator_loop(self):
        while self.running:
            time.sleep(2)  # enviar com frequência mais alta quando Lider
            if self.state == "LEADING":
                with self.peers_lock:
                    # preparar lista de peers (uuid, info), excluindo a mim mesmo
                    valid = [(uid, info) for uid, info in self.peers.items() if info.get("ip") and info.get("port") and uid != self.worker_uuid]

                if not valid:
                    self.log("Sou Leader, mas não há peers disponíveis para distribuir tarefas")
                    continue

                uid, target = random.choice(valid)
                task_msg = {"TASK": "TASK_EXEC", "DATA": f"Query_{random.randint(100,999)}"}
                self.log(f"Leader enviando TASK_EXEC a {target['ip']}:{target['port']} (peer {uid}) — {task_msg['DATA']}")
                ok = self._send_tcp(target["ip"], target["port"], task_msg)
                if not ok:
                    self.log(f"Falha ao enviar TASK_EXEC a {target['ip']}:{target['port']} (peer {uid})")

    # ───────────────────────────────────────────────────────────
    # CLIENT TCP para conexão com Master (apresentação / execução de tasks)
    # ───────────────────────────────────────────────────────────

    def _send_line(self, conn, payload: dict):
        try:
            data = json.dumps(payload) + "\n"
            conn.sendall(data.encode())
            return True
        except Exception:
            return False

    def _master_client_loop(self, host=MASTER_HOST, port=MASTER_PORT):
        while self.running:
            try:
                # always use instance-configured master host/port (tests set these on instance)
                host = self.master_host
                port = self.master_port

                discover_mode = host == "0.0.0.0" and not self.master_discovered
                if discover_mode:
                    if self.master_discovery_time is None:
                        self.master_discovery_time = time.time()
                    if time.time() - self.master_discovery_time < MASTER_DISCOVERY_WAIT:
                        self.log("Tentando descobrir Master via UDP...")
                        self.discovery_broadcast()
                        time.sleep(1)
                        continue
                    self.log("Nenhum Master descoberto via UDP; iniciando eleição Bully")
                    threading.Thread(target=self.start_election, daemon=True).start()
                    return

                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(5)
                    s.connect((host, port))
                    s.settimeout(None)
                    # Apresentação - se foi transferido, incluir SERVER_UUID do master original (host:port)
                    server_uuid = None
                    if self.original_master_host and self.original_master_port:
                        server_uuid = f"{self.original_master_host}:{self.original_master_port}"
                    
                    presentation = {
                        "WORKER": "ALIVE",
                        "WORKER_UUID": self.worker_uuid,
                        "SERVER_UUID": server_uuid
                    }
                    self.log(f"Conectado ao Master {host}:{port} — apresentando-se {self.worker_uuid}" + 
                            (f" (emprestado de {server_uuid})" if server_uuid else " (local)"))
                    self._send_line(s, presentation)

                    # If we were redirected (Sprint 3), register as temporary worker at new master
                    try:
                        if self.original_master_host and self.redirect_request_id:
                            reg = {
                                "type": "register_temporary_worker",
                                "request_id": self.redirect_request_id,
                                "payload": {
                                    "worker_id": self.worker_uuid,
                                    "original_master_address": f"{self.original_master_host}:{self.original_master_port}"
                                }
                            }
                            self._send_line(s, reg)
                            # clear the redirect id after registration
                            self.redirect_request_id = None
                    except Exception:
                        pass

                    # iniciar heartbeat thread (envia HEARTBEAT periodicamente)
                    def _hb_loop(sock):
                        try:
                            while self.running:
                                hb = {"SERVER_UUID": self.worker_uuid, "TASK": "HEARTBEAT"}
                                try:
                                    self._send_line(sock, hb)
                                except Exception:
                                    break
                                time.sleep(max(5, HEARTBEAT_INTERVAL))
                        except Exception:
                            pass

                    threading.Thread(target=_hb_loop, args=(s,), daemon=True).start()

                    # Loop de recebimento de mensagens delimitadas por \n
                    buffer = b""
                    while self.running:
                        chunk = s.recv(4096)
                        if not chunk:
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            try:
                                msg = json.loads(line.decode())
                            except Exception:
                                continue

                            task = msg.get("TASK")
                            # Sprint 3: handle master->master redirect command
                            if msg.get("type") == "command_redirect" or task == "command_redirect":
                                # payload contains new_master_address and original_master_address
                                payload = msg.get("payload", {})
                                addr = payload.get("new_master_address") or payload.get("new_host")
                                req_id = msg.get("request_id") or msg.get("REQUEST_ID")
                                if addr and ":" in addr:
                                    parts = addr.split(":")
                                    try:
                                        new_h = parts[0]
                                        new_p = int(parts[1])
                                    except Exception:
                                        continue
                                    self.log(f"Instrução command_redirect recebida: {new_h}:{new_p}")
                                    # guardar master atual antes de transferir
                                    self.original_master_host = self.master_host
                                    self.original_master_port = self.master_port
                                    # store request id to use on register at new master
                                    self.redirect_request_id = req_id
                                    # inform current master (best-effort) about transfer
                                    try:
                                        transfer_notice = {"TASK": "TRANSFER_COMPLETE", "WORKER_UUID": self.worker_uuid, "NEW_HOST": new_h, "NEW_PORT": new_p, "REQUEST_ID": req_id}
                                        self._send_line(s, transfer_notice)
                                    except Exception:
                                        pass
                                    # set new master and trigger reconnect
                                    self.master_host = new_h
                                    self.master_port = new_p
                                    raise RuntimeError("TRANSFER")
                            if task == "QUERY":
                                self.last_master_no_task = False
                                self.log(f"Recebido TASK from Master: {msg.get('USER')}")
                                # Simula processamento
                                time.sleep(random.uniform(0.2, 1.0))
                                status = {"STATUS": "OK", "TASK": "QUERY", "WORKER_UUID": self.worker_uuid}
                                self._send_line(s, status)

                                try:
                                    s.settimeout(2)
                                    # Usa o buffer do loop principal para não perder pacotes colados!
                                    while b"\n" not in buffer:
                                        chunk2 = s.recv(4096)
                                        if not chunk2: break
                                        buffer += chunk2
                                    
                                    if b"\n" in buffer:
                                        # Atualiza o buffer principal com a sobra (que pode ser a próxima TASK)
                                        ack_line, buffer = buffer.split(b"\n", 1)
                                        try:
                                            ack = json.loads(ack_line.decode())
                                            if ack.get("STATUS") == "ACK":
                                                self.log(f"ACK recebido do Master para {self.worker_uuid}")
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                                finally:
                                    s.settimeout(None)
                                # ==========================================
                                
                            elif task == "NO_TASK":
                                if not self.last_master_no_task:
                                    self.log("Master está sem tarefas no momento")
                                    self.last_master_no_task = True
                                continue
                            elif task == "TRANSFER_INSTRUCT":
                                # instrução para conectar a novo master (Sprint 2-3)
                                new_host = msg.get("HOST")
                                new_port = msg.get("PORT")
                                req_id = msg.get("REQUEST_ID")
                                if new_host and new_port:
                                    self.log(f"Instrução de transferência recebida: {new_host}:{new_port}")
                                    # Guardar o master atual antes de transferir (para later return via command_release)
                                    self.original_master_host = self.master_host
                                    self.original_master_port = self.master_port
                                    # notificar master atual que vou transferir
                                    try:
                                        transfer_notice = {"TASK": "TRANSFER_COMPLETE", "WORKER_UUID": self.worker_uuid, "NEW_HOST": new_host, "NEW_PORT": new_port, "REQUEST_ID": req_id}
                                        self._send_line(s, transfer_notice)
                                    except Exception:
                                        pass
                                    # gravar novo master e encerrar conexão atual para reconectar
                                    self.master_host = new_host
                                    self.master_port = new_port
                                    raise RuntimeError("TRANSFER")
                            elif task == "command_release" or msg.get("type") == "command_release":
                                # Instrução do Master para retornar ao master original (Sprint 3, seção 2.5.a)
                                orig_addr = msg.get("payload", {}).get("original_master_address", "")
                                if orig_addr and ":" in orig_addr:
                                    parts = orig_addr.split(":")
                                    try:
                                        ret_host = parts[0]
                                        ret_port = int(parts[1])
                                        self.log(f"Recebido COMMAND_RELEASE: retornando a {ret_host}:{ret_port}")
                                        # Reconectar ao master original
                                        self.master_host = ret_host
                                        self.master_port = ret_port
                                        self.original_master_host = None  # Clear para evitar confusão
                                        self.original_master_port = None
                                        raise RuntimeError("RELEASE")  # Sinal para reconectar
                                    except (ValueError, IndexError):
                                        self.log(f"Erro ao parsear command_release: {orig_addr}")
                    # conexão caiu — tentar reconectar
            except Exception as e:
                if isinstance(e, RuntimeError) and str(e) == "TRANSFER":
                    # reinicia loop para conectar ao novo master imediatamente
                    continue
                elif isinstance(e, RuntimeError) and str(e) == "RELEASE":
                    # Liberado pelo master anterior, reconectar ao master original
                    self.log("Liberado do master temporário, retornando ao master original")
                    continue
                self.log(f"Master connection error: {e}")
                self.log("Master inacessível; tentando reconectar sem iniciar eleição")
                time.sleep(2)
                continue

    def start(self):
        self._setup_sockets()
        threading.Thread(target=self._udp_listener, daemon=True).start()
        threading.Thread(target=self._tcp_listener, daemon=True).start()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._monitor_leader_alive, daemon=True).start()
        threading.Thread(target=self._task_orchestrator_loop, daemon=True).start()
        threading.Thread(target=self._master_client_loop, daemon=True).start()
        
        self.discovery_broadcast()
        time.sleep(1)
        self.master_discovery_time = time.time()
        
        self.log(f"Worker {self.worker_uuid} (ID: {self.worker_id}) rodando na porta {self.tcp_port}")
        try:
            while self.running: time.sleep(1)
        except KeyboardInterrupt:
            self.running = False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Worker node for P2P cluster")
    parser.add_argument("--port", type=int, default=MY_ELECTION_TCP, help="TCP port for worker election and control")
    parser.add_argument("--master-host", default=MASTER_HOST, help="Master host or IP address to connect to")
    parser.add_argument("--master-port", type=int, default=MASTER_PORT, help="Master port to connect to")
    args = parser.parse_args()

    if args.master_host == "127.0.0.1":
        print("WARNING: master-host is set to 127.0.0.1. If this worker is running on another machine, set --master-host to the Master's LAN IP.")
    elif args.master_host == "0.0.0.0":
        print("INFO: master-host 0.0.0.0 será tratado como descoberta UDP. O Worker aguardará o MASTER_ANNOUNCE para obter o IP real.")

    worker = WorkerNode(port=args.port)
    worker.master_host = args.master_host
    worker.master_port = args.master_port
    worker.start()
