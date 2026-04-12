import socket
import json
import threading
import time
import signal
import sys
import queue
import random
import string
from collections import deque

# ═══════════════════════════════════════════════════════════════
# CONFIGURAÇÃO
# ═══════════════════════════════════════════════════════════════
MASTER_UUID   = "Master_A"          
HOST          = "0.0.0.0"
PORT          = 5000
THRESHOLD     = 5                   
TASK_INTERVAL = 4                   


class MasterNode:
    def __init__(self, host=HOST, port=PORT):
        self.host        = host
        self.port        = port
        self.running     = True
        self.server_sock = None

        # Fila de tarefas pendentes (O2 — simula requisições de clientes)
        self.task_queue  = queue.Queue()
        self._start_task_generator()

        # Registro de workers conectados { worker_uuid: {"conn": ..., "borrowed_from": ...} }
        self.workers     = {}
        self.workers_lock = threading.Lock()

        # Log de tarefas concluídas
        self.completed_log = []
        self.log_lock      = threading.Lock()

    # ───────────────────────────────────────────────────────────
    # Gerador de tarefas simuladas (O2)
    # ───────────────────────────────────────────────────────────
    def _start_task_generator(self):
        def generate():
            users = ["Michel", "Julia", "Carlos", "Ana", "Pedro", "Laura"]
            while self.running:
                user = random.choice(users)
                self.task_queue.put({"TASK": "QUERY", "USER": user})
                load = self.task_queue.qsize()
                print(f"[FILA] Nova tarefa adicionada (USER={user}). Fila atual: {load} | Threshold: {THRESHOLD}")
                time.sleep(TASK_INTERVAL)
        threading.Thread(target=generate, daemon=True).start()

    # ───────────────────────────────────────────────────────────
    # Envio seguro de JSON com delimitador \n
    # ───────────────────────────────────────────────────────────
    def _send(self, conn, payload: dict):
        data = json.dumps(payload) + "\n"
        conn.sendall(data.encode())

    # ───────────────────────────────────────────────────────────
    # Recebimento de uma linha JSON completa
    # ───────────────────────────────────────────────────────────
    def _recv_line(self, conn) -> dict | None:
        buf = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return None
            buf += chunk
            if b"\n" in buf:
                line, _ = buf.split(b"\n", 1)
                return json.loads(line.decode().strip())

    # ───────────────────────────────────────────────────────────
    # Validação de payload (Strict Parsing — nota de impl. #1)
    # ───────────────────────────────────────────────────────────
    def _validate(self, payload: dict, required: list) -> bool:
        for field in required:
            if field not in payload:
                print(f"[ERRO] Campo obrigatório ausente: {field} em {payload}")
                return False
        return True

    # ───────────────────────────────────────────────────────────
    # Handler de worker: detecta o tipo e roteia
    # ───────────────────────────────────────────────────────────
    def handle_worker(self, conn, addr):
        print(f"[CONEXÃO] Worker conectado de {addr}")
        conn.settimeout(10)
        worker_uuid = None

        try:
            while self.running:
                try:
                    payload = self._recv_line(conn)
                    if payload is None:
                        break

                    task = payload.get("TASK", "").upper()

                    # ── HEARTBEAT (Sprint 1) ──────────────────
                    if task == "HEARTBEAT":
                        if not self._validate(payload, ["SERVER_UUID", "TASK"]):
                            continue
                        uid = payload["SERVER_UUID"]
                        print(f"[HEARTBEAT] {uid} — Status: ALIVE")
                        resp = {
                            "SERVER_UUID": MASTER_UUID,
                            "TASK":        "HEARTBEAT",
                            "RESPONSE":    "ALIVE"
                        }
                        self._send(conn, resp)

                    # ── APRESENTAÇÃO DE WORKER (Sprint 2 — Tarefa 01) ──
                    elif payload.get("WORKER") == "ALIVE":
                        if not self._validate(payload, ["WORKER", "WORKER_UUID"]):
                            continue

                        worker_uuid   = payload["WORKER_UUID"]
                        borrowed_from = payload.get("SERVER_UUID")  

                        with self.workers_lock:
                            self.workers[worker_uuid] = {
                                "conn":          conn,
                                "addr":          addr,
                                "borrowed_from": borrowed_from,
                                "busy":          False
                            }

                        if borrowed_from:
                            print(f"[WORKER] {worker_uuid} apresentado (EMPRESTADO de {borrowed_from})")
                        else:
                            print(f"[WORKER] {worker_uuid} apresentado (LOCAL)")

                        
                        self._dispatch_task(conn, worker_uuid)

                    # ── REPORTE DE STATUS ──
                    elif payload.get("STATUS") in ("OK", "NOK"):
                        if not self._validate(payload, ["STATUS", "TASK", "WORKER_UUID"]):
                            continue

                        status      = payload["STATUS"]
                        task_done   = payload["TASK"]
                        w_uuid      = payload["WORKER_UUID"]
                        emoji       = "✓" if status == "OK" else "✗"

                        with self.log_lock:
                            self.completed_log.append({
                                "worker":    w_uuid,
                                "task":      task_done,
                                "status":    status,
                                "timestamp": time.strftime("%H:%M:%S")
                            })

                        print(f"[STATUS] {emoji} Worker {w_uuid} — TASK={task_done} STATUS={status}")

                        
                        ack = {"STATUS": "ACK", "WORKER_UUID": w_uuid}
                        self._send(conn, ack)
                        print(f"[ACK]    → {w_uuid} liberado")

                        
                        with self.workers_lock:
                            if w_uuid in self.workers:
                                self.workers[w_uuid]["busy"] = False

                        self._dispatch_task(conn, w_uuid)

                    else:
                        print(f"[AVISO] Payload desconhecido de {addr}: {payload}")

                except socket.timeout:
                    continue
                except json.JSONDecodeError as e:
                    print(f"[ERRO JSON] {e}")
                    continue

        except Exception as e:
            if self.running:
                print(f"[ERRO] Conexão com {addr}: {e}")
        finally:
            if worker_uuid:
                with self.workers_lock:
                    self.workers.pop(worker_uuid, None)
            conn.close()
            print(f"[CONEXÃO] Worker {worker_uuid or addr} desconectado")

    # ───────────────────────────────────────────────────────────
    # Distribui tarefa ao worker 
    # ───────────────────────────────────────────────────────────
    def _dispatch_task(self, conn, worker_uuid: str):
        try:
            task = self.task_queue.get_nowait()
            
            self._send(conn, task)
            print(f"[DISPATCH] Tarefa enviada a {worker_uuid}: USER={task.get('USER')}")
            with self.workers_lock:
                if worker_uuid in self.workers:
                    self.workers[worker_uuid]["busy"] = True
        except queue.Empty:
            
            self._send(conn, {"TASK": "NO_TASK"})
            print(f"[DISPATCH] Sem tarefas para {worker_uuid} — NO_TASK enviado")

    # ───────────────────────────────────────────────────────────
    # Monitor de saturação 
    # ───────────────────────────────────────────────────────────
    def _monitor_saturation(self):
        while self.running:
            load = self.task_queue.qsize()
            if load >= THRESHOLD:
                print(f"\n[⚠ SATURAÇÃO] Fila={load} ≥ Threshold={THRESHOLD} — Protocolo consensual necessário (O4/O5)")
            time.sleep(5)

    # ───────────────────────────────────────────────────────────
    # Início do servidor TCP
    # ───────────────────────────────────────────────────────────
    def start(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(20)
        self.server_sock.settimeout(1)

        threading.Thread(target=self._monitor_saturation, daemon=True).start()

        print(f"\n{'═'*55}")
        print(f"  MASTER [{MASTER_UUID}] ONLINE — {self.host}:{self.port}")
        print(f"  Threshold de saturação: {THRESHOLD} tarefas")
        print(f"{'═'*55}\n")

        while self.running:
            try:
                conn, addr = self.server_sock.accept()
                threading.Thread(
                    target=self.handle_worker,
                    args=(conn, addr),
                    daemon=True
                ).start()
            except socket.timeout:
                continue

    def shutdown(self):
        print(f"\n[MASTER] Encerrando {MASTER_UUID}...")
        self.running = False
        try:
            self.server_sock.close()
        except:
            pass


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════
master = None

def signal_handler(sig, frame):
    if master:
        master.shutdown()
    sys.exit(0)

if __name__ == "__main__":
    master = MasterNode()
    signal.signal(signal.SIGINT, signal_handler)
    try:
        master.start()
    finally:
        print("[MASTER] Finalizado")