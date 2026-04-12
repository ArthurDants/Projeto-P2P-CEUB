import socket
import json
import time
import shutil
import threading
import signal
import sys
import os
import random

# ═══════════════════════════════════════════════════════════════
# CONFIGURAÇÃO — ajuste por máquina
# ═══════════════════════════════════════════════════════════════
WORKER_UUID       = "WORKER-A1"       
MASTER_HOST       = "10.62.206.31"    
MASTER_PORT       = 5000
BORROWED_FROM     = None              

HEARTBEAT_INTERVAL = 30              
HEARTBEAT_TIMEOUT  = 5               
MAX_FAILURES       = 4               

# Portas para eleição por broadcast UDP
ELECTION_UDP_PORT  = 5002            
MY_ELECTION_TCP    = 5003            
                                     


class WorkerNode:
    def __init__(self):
        self.worker_uuid   = WORKER_UUID
        self.master_host   = MASTER_HOST
        self.master_port   = MASTER_PORT
        self.borrowed_from = BORROWED_FROM
        self.running       = True
        self.conn_failures = 0

    # ───────────────────────────────────────────────────────────
    # Utilitários
    # ───────────────────────────────────────────────────────────
    def _free_disk_gb(self) -> float:
        return shutil.disk_usage("/").free / (1024 ** 3)

    def _local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

    def _send(self, conn, payload: dict):
        """Envia JSON com delimitador \\n (Message Delimiter — impl. #1)."""
        conn.sendall((json.dumps(payload) + "\n").encode())

    def _recv_line(self, conn) -> dict | None:
        """Lê até encontrar \\n, retorna dict ou None."""
        buf = b""
        conn.settimeout(HEARTBEAT_TIMEOUT)
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return None
            buf += chunk
            if b"\n" in buf:
                line, _ = buf.split(b"\n", 1)
                return json.loads(line.decode().strip())

    
    def _heartbeat_loop(self, conn):
        """Loop de heartbeat dentro de uma conexão ativa."""
        while self.running:
            try:
                
                payload = {
                    "SERVER_UUID": self.worker_uuid,
                    "TASK":        "HEARTBEAT"
                }
                self._send(conn, payload)
                print(f"[HEARTBEAT] → Enviado ao master")

                resp = self._recv_line(conn)
                if resp and resp.get("RESPONSE") == "ALIVE":
                    print(f"[HEARTBEAT] ← Status: ALIVE")
                    self.conn_failures = 0
                else:
                    raise ConnectionError("Resposta inválida no heartbeat")

            except (socket.timeout, ConnectionError, OSError) as e:
                self.conn_failures += 1
                print(f"[HEARTBEAT] ⚠ Falha {self.conn_failures}/{MAX_FAILURES}: {e}")
                if self.conn_failures >= MAX_FAILURES:
                    print(f"[HEARTBEAT] 🚨 MASTER OFFLINE — iniciando eleição")
                    return  

            time.sleep(HEARTBEAT_INTERVAL)

    def _task_cycle(self, conn):
       
        # ── Passo 1: Apresentação ────────────────────────────
        presentation = {
            "WORKER":      "ALIVE",
            "WORKER_UUID": self.worker_uuid
        }
        if self.borrowed_from:
            # Payload 2.1b — worker emprestado
            presentation["SERVER_UUID"] = self.borrowed_from
            print(f"[APRESENTAÇÃO] Identificando como emprestado de {self.borrowed_from}")
        else:
            print(f"[APRESENTAÇÃO] Identificando como worker local")

        self._send(conn, presentation)

        while self.running:
            try:
                # ── Passo 2: Recebe tarefa ───────────────────
                task_payload = self._recv_line(conn)
                if task_payload is None:
                    print("[TAREFA] Conexão perdida durante espera de tarefa")
                    return

                task_type = task_payload.get("TASK", "").upper()

                if task_type == "NO_TASK":
                    
                    print(f"[TAREFA] Sem tarefas — aguardando próximo ciclo ({HEARTBEAT_INTERVAL}s)")
                    time.sleep(HEARTBEAT_INTERVAL)
                    
                    self._send(conn, presentation)
                    continue

                elif task_type == "QUERY":
                    user = task_payload.get("USER", "?")
                    print(f"[TAREFA] ← QUERY recebida (USER={user})")

                    # ── Passo 3: Processamento simulado ──────
                    sleep_time = random.uniform(1, 4)
                    print(f"[PROCESSAMENTO] Simulando {sleep_time:.1f}s de trabalho...")
                    time.sleep(sleep_time)

                
                    status = "OK" if random.random() > 0.1 else "NOK"

                    # ── Passo 4: Reporte de status ────────────
                   
                    status_report = {
                        "STATUS":      status,
                        "TASK":        "QUERY",
                        "WORKER_UUID": self.worker_uuid
                    }
                    self._send(conn, status_report)
                    emoji = "✓" if status == "OK" else "✗"
                    print(f"[STATUS] {emoji} Reportado: {status}")

                    # ── Passo 5: Aguarda ACK ─────────────────
                    ack = self._recv_line(conn)
                    if ack and ack.get("STATUS") == "ACK":
                        print(f"[ACK] ← Recebido — liberado para próximo ciclo")
                    else:
                        print(f"[ACK] ⚠ ACK inesperado: {ack}")

                    
                    self._send(conn, presentation)

                else:
                    print(f"[TAREFA] ⚠ TASK desconhecida: {task_type}")

            except socket.timeout:
                print(f"[TAREFA] Timeout aguardando master — tentando reconectar")
                return
            except (ConnectionError, OSError) as e:
                print(f"[TAREFA] Erro de conexão: {e}")
                return
            except json.JSONDecodeError as e:
                print(f"[TAREFA] Erro JSON: {e}")

    # ═══════════════════════════════════════════════════════════
    # Loop principal de conexão ao master
    # ═══════════════════════════════════════════════════════════
    def _connect_and_run(self):
        """Conecta ao master e executa heartbeat + ciclo de tarefas em paralelo."""
        while self.running:
            print(f"\n[WORKER] Conectando a {self.master_host}:{self.master_port}...")
            try:
                conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                conn.settimeout(5)
                conn.connect((self.master_host, self.master_port))
                conn.settimeout(None)  
                print(f"[WORKER] ✓ Conectado!")
                self.conn_failures = 0

                # Roda heartbeat em thread separada (não bloqueia o ciclo de tarefas)
                hb_stop = threading.Event()

                def heartbeat_thread():
                    """Heartbeat independente na mesma conexão TCP."""
                    hb_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        hb_conn.settimeout(5)
                        hb_conn.connect((self.master_host, self.master_port))
                        while self.running and not hb_stop.is_set():
                            try:
                                payload = {
                                    "SERVER_UUID": self.worker_uuid,
                                    "TASK":        "HEARTBEAT"
                                }
                                self._send(hb_conn, payload)
                                resp = self._recv_line(hb_conn)
                                if resp and resp.get("RESPONSE") == "ALIVE":
                                    print(f"[HEARTBEAT] ← ALIVE")
                                    self.conn_failures = 0
                                else:
                                    raise ConnectionError("Sem resposta ALIVE")
                            except Exception as e:
                                self.conn_failures += 1
                                print(f"[HEARTBEAT] ⚠ {self.conn_failures}/{MAX_FAILURES}: {e}")
                                if self.conn_failures >= MAX_FAILURES:
                                    hb_stop.set()
                                    break
                            time.sleep(HEARTBEAT_INTERVAL)
                    finally:
                        hb_conn.close()

                hb_thread = threading.Thread(target=heartbeat_thread, daemon=True)
                hb_thread.start()

                
                self._task_cycle(conn)

                hb_stop.set()
                conn.close()

                # Se master caiu (detectado por heartbeat ou task cycle)
                if self.conn_failures >= MAX_FAILURES:
                    self._initiate_election()
                    self.conn_failures = 0

            except (ConnectionRefusedError, OSError) as e:
                self.conn_failures += 1
                print(f"[WORKER] ✗ Falha ao conectar: {e} ({self.conn_failures}/{MAX_FAILURES})")
                if self.conn_failures >= MAX_FAILURES:
                    self._initiate_election()
                    self.conn_failures = 0
                else:
                    time.sleep(5)

    # ═══════════════════════════════════════════════════════════
    # ELEIÇÃO POR BROADCAST UDP
    # ═══════════════════════════════════════════════════════════
    def _listen_for_elections(self):
        """Escuta broadcasts UDP de ELECTION_QUERY e responde via TCP."""
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp.bind(("0.0.0.0", ELECTION_UDP_PORT))
        udp.settimeout(1)
        print(f"[ELEIÇÃO] Escutando UDP na porta {ELECTION_UDP_PORT}")

        while self.running:
            try:
                data, addr = udp.recvfrom(1024)
                payload = json.loads(data.decode().strip())

                if payload.get("TASK") == "ELECTION_QUERY":
                    print(f"[ELEIÇÃO] 📢 Broadcast recebido de {addr}")
                    reply_port = payload.get("REPLY_TCP_PORT", MY_ELECTION_TCP)
                    response = {
                        "SERVER_UUID": self.worker_uuid,
                        "IP":          self._local_ip(),
                        "TCP_PORT":    MY_ELECTION_TCP,
                        "FREE_DISK_GB": self._free_disk_gb()
                    }
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
                            tcp.settimeout(3)
                            tcp.connect((addr[0], reply_port))
                            tcp.sendall((json.dumps(response) + "\n").encode())
                    except Exception as e:
                        print(f"[ELEIÇÃO] Erro ao responder: {e}")

            except socket.timeout:
                continue
            except Exception as e:
                print(f"[ELEIÇÃO] Erro listener: {e}")

        udp.close()

    def _collect_election_responses(self, timeout=3.0) -> list:
        """Abre TCP temporário e coleta respostas dos outros workers."""
        responses = []
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", MY_ELECTION_TCP))
        srv.listen(20)
        srv.settimeout(timeout)
        deadline = time.time() + timeout

        try:
            while time.time() < deadline:
                try:
                    c, _ = srv.accept()
                    c.settimeout(2)
                    data = c.recv(1024).decode().strip()
                    c.close()
                    resp = json.loads(data)
                    print(f"[ELEIÇÃO] {resp['SERVER_UUID']} → {resp['FREE_DISK_GB']:.2f} GB")
                    responses.append(resp)
                except socket.timeout:
                    break
        finally:
            srv.close()
        return responses

    def _initiate_election(self):
        print(f"\n{'═'*55}")
        print(f"[ELEIÇÃO] {self.worker_uuid} iniciando eleição por broadcast UDP")
        print(f"{'═'*55}")

        responses_holder = []

        def collect():
            responses_holder.extend(self._collect_election_responses(timeout=3.0))

        collector = threading.Thread(target=collect, daemon=True)
        collector.start()
        time.sleep(0.1)  

        # Broadcast UDP
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        broadcast = json.dumps({
            "TASK":           "ELECTION_QUERY",
            "REPLY_TCP_PORT": MY_ELECTION_TCP
        }).encode()
        try:
            udp.sendto(broadcast, ("255.255.255.255", ELECTION_UDP_PORT))
            print(f"[ELEIÇÃO] Broadcast enviado → {ELECTION_UDP_PORT}")
        except Exception as e:
            print(f"[ELEIÇÃO] Erro broadcast: {e}")
        finally:
            udp.close()

        collector.join()

        # Inclui o próprio worker
        candidates = [{
            "SERVER_UUID":  self.worker_uuid,
            "IP":           self._local_ip(),
            "TCP_PORT":     MY_ELECTION_TCP,
            "FREE_DISK_GB": self._free_disk_gb()
        }] + responses_holder

        print(f"\n[ELEIÇÃO] {len(candidates)} candidato(s):")
        for c in candidates:
            me = " ← (eu)" if c["SERVER_UUID"] == self.worker_uuid else ""
            print(f"  {c['SERVER_UUID']:20s} | {c['FREE_DISK_GB']:7.2f} GB{me}")

        eleito = max(candidates, key=lambda x: x["FREE_DISK_GB"])
        print(f"\n🏆 ELEITO: {eleito['SERVER_UUID']} ({eleito['FREE_DISK_GB']:.2f} GB livres)")

        if eleito["SERVER_UUID"] == self.worker_uuid:
            print(f"[ELEIÇÃO] 👑 EU SOU O NOVO MASTER — iniciando MasterNode...")
            from master import MasterNode
            new_master = MasterNode()
            threading.Thread(target=new_master.start, daemon=True).start()
            self.master_host = self._local_ip()
            self.master_port = MASTER_PORT
            time.sleep(2)  
        else:
            self.master_host = eleito["IP"]
            self.master_port = MASTER_PORT
            print(f"[ELEIÇÃO] Apontando para novo master: {self.master_host}:{self.master_port}")

        print(f"{'═'*55}\n")

    # ═══════════════════════════════════════════════════════════
    # START
    # ═══════════════════════════════════════════════════════════
    def run(self):
        print(f"\n{'═'*55}")
        print(f"  WORKER [{self.worker_uuid}]")
        print(f"  IP local : {self._local_ip()}")
        print(f"  Master   : {self.master_host}:{self.master_port}")
        print(f"  Emprestado de: {self.borrowed_from or 'N/A (local)'}")
        print(f"{'═'*55}\n")

        
        threading.Thread(target=self._listen_for_elections, daemon=True).start()

        
        self._connect_and_run()

    def shutdown(self):
        print(f"\n[WORKER] Encerrando {self.worker_uuid}...")
        self.running = False


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════
worker = None

def signal_handler(sig, frame):
    if worker:
        worker.shutdown()
    sys.exit(0)

if __name__ == "__main__":
    worker = WorkerNode()
    signal.signal(signal.SIGINT, signal_handler)
    try:
        worker.run()
    finally:
        print(f"[WORKER] {worker.worker_uuid} finalizado")
        os._exit(0)