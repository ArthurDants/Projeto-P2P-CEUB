import argparse
import socket
import json
import threading
import time
import signal
import sys
import queue
import random
import os
import uuid

# Basic configuration
MASTER_UUID = "Master_A"
HOST = "0.0.0.0"
PORT = 10000
ELECTION_UDP_PORT = 5002
MASTER_DISCOVERY_INTERVAL = 8
THRESHOLD = 5
RELEASE_THRESHOLD = 2  # Histerese: libera workers quando carga cai abaixo disso
TASK_INTERVAL = 4
MASTER_PEERS = []
FIXED_PARTNER_PEERS = [("10.62.206.21", 10000)]
CAPACITY = 100
LOG_DIR = "logs"
LOG_FILE = f"{LOG_DIR}/tasks.log"
PENDING_TTL = 8
MAX_INSTRUCT_RETRIES = 2
COMMAND_RELEASE_TIMEOUT = 3  # Timeout para enviar command_release


class MasterNode:
    def __init__(self, host=HOST, port=PORT):
        self.host = host
        self.port = port
        self.running = True
        self.server_sock = None

        self.task_queue = queue.Queue()
        self._start_task_generator()

        self.workers = {}
        self.workers_lock = threading.Lock()
        self.next_worker_index = 0
        self.master_peers = list(MASTER_PEERS)

        # pending_borrows: REQUEST_ID -> {from, host, port, target:list, acked:list, timestamp, attempts}
        self.pending_borrows = {}
        self.pending_lock = threading.Lock()

        self.completed_log = []
        self.log_lock = threading.Lock()
        self.borrow_cooldowns = {}
        
        # workers_borrowed: {worker_uuid: {original_master_host, original_master_port, borrowed_from_host, borrowed_from_port}}
        self.workers_borrowed = {}
        self.borrowed_lock = threading.Lock()
        self.udp_sock = None

    def _start_task_generator(self):
        def gen():
            users = ["Michel", "Julia", "Carlos", "Ana", "Pedro", "Laura"]
            while self.running:
                user = random.choice(users)
                self.task_queue.put({"TASK": "QUERY", "USER": user})
                print(f"[FILA] Nova tarefa adicionada (USER={user}). Fila atual: {self.task_queue.qsize()} | Threshold: {THRESHOLD}")
                self._dispatch_idle_workers()
                time.sleep(TASK_INTERVAL)
        threading.Thread(target=gen, daemon=True).start()

    def _send(self, conn, payload: dict):
        data = json.dumps(payload) + "\n"
        conn.sendall(data.encode())

    def _send_line(self, conn, payload: dict):
        try:
            data = json.dumps(payload) + "\n"
            conn.sendall(data.encode())
            return True
        except Exception:
            return False

    def _send_text(self, conn, text: str):
        try:
            conn.sendall((text + "\n").encode())
            return True
        except Exception:
            return False

    def _persist_log(self, entry: dict):
        try:
            if not os.path.isdir(LOG_DIR):
                os.makedirs(LOG_DIR, exist_ok=True)
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[LOG-ERR] {e}")

    def _recv_line(self, conn_file):
        line = conn_file.readline()
        if not line:
            return None
        text = line.decode().strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _validate(self, payload: dict, required: list) -> bool:
        for f in required:
            if f not in payload:
                print(f"[ERRO] Campo obrigatório ausente: {f} em {payload}")
                return False
        return True

    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _get_local_broadcast(self) -> str:
        try:
            local_ip = self._get_local_ip()
            parts = local_ip.split('.')
            if len(parts) == 4:
                parts[-1] = '255'
                return '.'.join(parts)
        except Exception:
            pass
        return '255.255.255.255'

    def _add_master_peer(self, host: str, port: int):
        if host == self._get_local_ip() and port == self.port:
            return
        if (host, port) not in self.master_peers:
            self.master_peers.append((host, port))
            print(f"[PEER] Novo master descoberto: {host}:{port}")

    def _setup_udp_socket(self):
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.udp_sock.bind(("", ELECTION_UDP_PORT))

    def _master_udp_listener(self):
        while self.running:
            try:
                data, addr = self.udp_sock.recvfrom(4096)
                msg = json.loads(data.decode())
                task = msg.get("TASK")
                if task == "DISCOVERY":
                    print(f"[UDP] Discovery recebido de {addr}")
                    announce = {
                        "TASK": "MASTER_ANNOUNCE",
                        "HOST": self._get_local_ip(),
                        "PORT": self.port,
                        "MASTER_UUID": MASTER_UUID
                    }
                    self.udp_sock.sendto(json.dumps(announce).encode(), addr)
                    print(f"[UDP] Enviado MASTER_ANNOUNCE para {addr}")
                elif task == "MASTER_DISCOVERY":
                    sender_host = msg.get("HOST") or addr[0]
                    sender_port = int(msg.get("PORT") or addr[1])
                    if sender_host == self._get_local_ip() and sender_port == self.port:
                        continue
                    print(f"[UDP] Master discovery recebido de {sender_host}:{sender_port}")
                    self._add_master_peer(sender_host, sender_port)
                    announce = {
                        "TASK": "MASTER_PEER_ANNOUNCE",
                        "HOST": self._get_local_ip(),
                        "PORT": self.port,
                        "MASTER_UUID": MASTER_UUID
                    }
                    self.udp_sock.sendto(json.dumps(announce).encode(), (sender_host, ELECTION_UDP_PORT))
                    print(f"[UDP] Enviado MASTER_PEER_ANNOUNCE para {sender_host}:{sender_port}")
                elif task == "MASTER_PEER_ANNOUNCE":
                    sender_host = msg.get("HOST") or addr[0]
                    sender_port = int(msg.get("PORT") or addr[1])
                    if sender_host == self._get_local_ip() and sender_port == self.port:
                        continue
                    print(f"[UDP] Master peer announce recebido de {sender_host}:{sender_port}")
                    self._add_master_peer(sender_host, sender_port)
            except Exception as e:
                print(f"[UDP-ERR] {e}")
                continue

    def _master_discovery_loop(self):
        while self.running:
            try:
                payload = {
                    "TASK": "MASTER_DISCOVERY",
                    "HOST": self._get_local_ip(),
                    "PORT": self.port,
                    "MASTER_UUID": MASTER_UUID
                }
                message = json.dumps(payload).encode()
                self.udp_sock.sendto(message, ("255.255.255.255", ELECTION_UDP_PORT))
                print(f"[UDP] Enviado MASTER_DISCOVERY broadcast 255.255.255.255")
                local_bcast = self._get_local_broadcast()
                if local_bcast != "255.255.255.255":
                    self.udp_sock.sendto(message, (local_bcast, ELECTION_UDP_PORT))
                    print(f"[UDP] Enviado MASTER_DISCOVERY broadcast local {local_bcast}")
                time.sleep(MASTER_DISCOVERY_INTERVAL)
            except Exception as e:
                print(f"[UDP-ERR] {getattr(e, 'args', e)}")
                time.sleep(MASTER_DISCOVERY_INTERVAL)

    def handle_worker(self, conn, addr):
        print(f"[CONEXÃO] Worker conectado de {addr}")
        conn.settimeout(10)
        conn_file = conn.makefile('rb')
        worker_uuid = None
        try:
            while self.running:
                try:
                    payload = self._recv_line(conn_file)
                    if payload is None:
                        break

                    if isinstance(payload, str):
                        msg_type = payload
                    elif isinstance(payload, dict):
                        msg_type = payload.get("type") or payload.get("TASK")
                    else:
                        msg_type = None

                    if msg_type in ("SPRINT2_WORKER_ALIVE", "SPRINT2_QUERY", "SPRINT2_OK", "SPRINT2_NOK"):
                        if msg_type == "SPRINT2_WORKER_ALIVE":
                            worker_uuid = f"SPRINT2-{addr[0]}:{addr[1]}"
                            with self.workers_lock:
                                self.workers[worker_uuid] = {"conn": conn, "addr": addr, "borrowed_from": None, "busy": False, "protocol": "sprint2", "last_task": None}
                            print(f"[WORKER] {worker_uuid} apresentado (SPRINT2 LOCAL)")
                            print(f"[REGISTERED] Master {self.port} added worker {worker_uuid} — total={len(self.workers)}")
                            continue

                        if msg_type == "SPRINT2_QUERY":
                            if not worker_uuid:
                                worker_uuid = f"SPRINT2-{addr[0]}:{addr[1]}"
                            task_text = None
                            try:
                                task = self.task_queue.get_nowait()
                                task_text = task.get("USER") or task.get("TASK") or str(task)
                                self._send_text(conn, task_text)
                                with self.workers_lock:
                                    info = self.workers.get(worker_uuid)
                                    if info is not None:
                                        info["busy"] = True
                                        info["last_task"] = task_text
                                print(f"[DISPATCH] SPRINT2 tarefa enviada a {worker_uuid}: {task_text}")
                            except queue.Empty:
                                self._send_text(conn, "NO_TASK")
                            continue

                        if msg_type in ("SPRINT2_OK", "SPRINT2_NOK"):
                            status = msg_type
                            task_done = None
                            with self.workers_lock:
                                info = self.workers.get(worker_uuid)
                                if info is not None:
                                    task_done = info.pop("last_task", None)
                                    info["busy"] = False
                            self._send_text(conn, "SPRINT2_ACK")
                            print(f"[STATUS] {'✓' if status=='SPRINT2_OK' else '✗'} Worker {worker_uuid} — TASK={task_done or '<unknown>'} STATUS={status}")
                            continue

                        continue

                    if isinstance(payload, str):
                        print(f"[SPRINT2] Mensagem desconhecida de {addr}: {payload}")
                        continue

                    task = payload.get("TASK", "").upper() if isinstance(payload, dict) else ""

                    if task == "HEARTBEAT":
                        if not self._validate(payload, ["SERVER_UUID", "TASK"]):
                            continue
                        uid = payload["SERVER_UUID"]
                        print(f"[HEARTBEAT] {uid} — ALIVE")
                        self._send(conn, {"SERVER_UUID": MASTER_UUID, "TASK": "HEARTBEAT", "RESPONSE": "ALIVE"})
                        continue

                    elif payload.get("type") == "register_temporary_worker":
                        inner = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
                        worker_uuid = inner.get("worker_id") or payload.get("worker_id")
                        borrowed_from = inner.get("original_master_address") or payload.get("original_master_address")
                        if not worker_uuid or not borrowed_from:
                            print(f"[ERRO] register_temporary_worker payload inválido de {addr}: {payload}")
                            continue
                        with self.workers_lock:
                            self.workers[worker_uuid] = {"conn": conn, "addr": addr, "borrowed_from": borrowed_from, "busy": False, "protocol": "sprint2", "last_task": None}
                        print(f"[WORKER] {worker_uuid} apresentado (SPRINT2 EMPRESTADO de {borrowed_from})")
                        print(f"[REGISTERED] Master {self.port} added worker {worker_uuid} — total={len(self.workers)}")
                        with self.borrowed_lock:
                            self.workers_borrowed[worker_uuid] = {
                                "original_master_host": borrowed_from.split(":", 1)[0],
                                "original_master_port": int(borrowed_from.split(":", 1)[1]),
                                "borrowed_from_host": addr[0],
                                "borrowed_from_port": addr[1],
                                "borrowed_from_uuid": None,
                            }
                        continue

                    elif payload.get("WORKER") == "ALIVE":
                        if not self._validate(payload, ["WORKER", "WORKER_UUID"]):
                            continue
                        worker_uuid = payload["WORKER_UUID"]
                        borrowed_from = payload.get("SERVER_UUID")
                        with self.workers_lock:
                            self.workers[worker_uuid] = {"conn": conn, "addr": addr, "borrowed_from": borrowed_from, "busy": False, "protocol": "legacy"}
                        print(f"[WORKER] {worker_uuid} apresentado ({'EMPRESTADO' if borrowed_from else 'LOCAL'})")
                        print(f"[REGISTERED] Master {self.port} added worker {worker_uuid} — total={len(self.workers)}")
                        
                        # Se worker é emprestado, registrar em workers_borrowed para rastreamento (Sprint 3)
                        if borrowed_from:
                            # borrowed_from format expected: "host:port"
                            orig_host = self.host
                            orig_port = self.port
                            if isinstance(borrowed_from, str) and ":" in borrowed_from:
                                parts = borrowed_from.split(":", 1)
                                orig_host = parts[0]
                                try:
                                    orig_port = int(parts[1])
                                except Exception:
                                    orig_port = self.port
                            with self.borrowed_lock:
                                self.workers_borrowed[worker_uuid] = {
                                    "original_master_host": orig_host,
                                    "original_master_port": orig_port,
                                    "borrowed_from_host": addr[0],
                                    "borrowed_from_port": addr[1]
                                }
                            print(f"[BORROWED] Worker {worker_uuid} rastreado para liberação posterior")
                        
                        self._dispatch_task(conn, worker_uuid)
                        self._dispatch_idle_workers()
                        continue

                    elif payload.get("STATUS") in ("OK", "NOK"):
                        if not self._validate(payload, ["STATUS", "TASK", "WORKER_UUID"]):
                            continue
                        status = payload["STATUS"]
                        task_done = payload["TASK"]
                        w_uuid = payload["WORKER_UUID"]
                        with self.log_lock:
                            self.completed_log.append({"worker": w_uuid, "task": task_done, "status": status, "timestamp": time.strftime("%H:%M:%S")})
                        self._persist_log({"worker": w_uuid, "task": task_done, "status": status, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")})
                        print(f"[STATUS] {'✓' if status=='OK' else '✗'} Worker {w_uuid} — TASK={task_done} STATUS={status}")
                        self._send(conn, {"STATUS": "ACK", "WORKER_UUID": w_uuid})
                        with self.workers_lock:
                            if w_uuid in self.workers:
                                self.workers[w_uuid]["busy"] = False
                        self._dispatch_task(conn, w_uuid)
                        self._dispatch_idle_workers()
                        continue

                    # Sprint3 Master-to-Master: request_help
                    if isinstance(payload, dict) and payload.get("type") == "request_help":
                        req_id = payload.get("request_id")
                        pl = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
                        workers_needed = int(pl.get("workers_needed", 0))
                        # Prefer explicit host/port from payload (originator's listening addr); fallback to TCP peer addr
                        from_host = pl.get("host") or addr[0]
                        try:
                            from_port = int(pl.get("port")) if pl.get("port") is not None else int(addr[1])
                        except Exception:
                            from_port = addr[1]

                        # idempotency
                        with self.pending_lock:
                            existing = self.pending_borrows.get(req_id)
                        if existing:
                            resp = {"type": "response_accepted", "request_id": req_id, "payload": {"workers_offered": len(existing.get("acked", [])), "worker_details": []}}
                            self._send_line(conn, resp)
                            continue

                        # select available workers
                        selected = []
                        details = []
                        with self.workers_lock:
                            for w_uuid, info in list(self.workers.items()):
                                if not info.get("busy") and not info.get("borrowed_from") and not info.get("borrowed_pending"):
                                    selected.append(w_uuid)
                                    addr_info = info.get("addr")
                                    address = f"{addr_info[0]}:{addr_info[1]}" if addr_info else "unknown"
                                    details.append({"id": w_uuid, "address": address})
                                    if len(selected) >= workers_needed:
                                        break

                        if not selected:
                            resp = {"type": "response_rejected", "request_id": req_id, "payload": {"reason": "no_workers_available"}}
                            self._send_line(conn, resp)
                            continue

                        with self.pending_lock:
                            self.pending_borrows[req_id] = {"from": payload.get("payload", {}).get("master_id"), "host": from_host, "port": from_port, "target": selected.copy(), "acked": [], "timestamp": time.time(), "attempts": 0}

                        acked = []
                        for w_uuid in selected:
                            with self.workers_lock:
                                info = self.workers.get(w_uuid)
                            if not info:
                                continue
                            try:
                                info["borrowed_pending"] = payload.get("payload", {}).get("master_id")
                                if info.get("protocol") == "sprint2":
                                    command = {
                                        "type": "command_redirect",
                                        "request_id": req_id,
                                        "payload": {
                                            "new_master_address": f"{from_host}:{from_port}",
                                            "original_master_address": f"{self.host}:{self.port}"
                                        }
                                    }
                                    ok = self._send_text(info["conn"], json.dumps(command))
                                else:
                                    instruct = {"TASK": "TRANSFER_INSTRUCT", "HOST": from_host, "PORT": from_port, "REQUEST_ID": req_id}
                                    ok = self._send_line(info["conn"], instruct)
                                if ok:
                                    acked.append(w_uuid)
                                    with self.borrowed_lock:
                                        self.workers_borrowed[w_uuid] = {
                                            "original_master_host": self.host,
                                            "original_master_port": self.port,
                                            "borrowed_from_host": from_host,
                                            "borrowed_from_port": from_port,
                                            "borrowed_from_uuid": payload.get("payload", {}).get("master_id")
                                        }
                                else:
                                    info.pop("borrowed_pending", None)
                            except Exception:
                                info.pop("borrowed_pending", None)

                        with self.pending_lock:
                            rec = self.pending_borrows.get(req_id)
                            if rec is not None:
                                rec["acked"] = acked

                        resp = {"type": "response_accepted", "request_id": req_id, "payload": {"workers_offered": len(acked), "worker_details": details}}
                        self._send_line(conn, resp)
                        continue

                    # Backwards-compatible legacy borrow request
                    elif task == "BORROW_REQUEST":
                        req_id = payload.get("REQUEST_ID")
                        num = int(payload.get("NUM", 0))
                        from_uuid = payload.get("FROM")
                        from_host = payload.get("HOST") or addr[0]
                        from_port = int(payload.get("PORT") or addr[1])

                        # idempotency
                        with self.pending_lock:
                            existing = self.pending_borrows.get(req_id)
                        if existing:
                            self._send_line(conn, {"TASK": "BORROW_RESPONSE", "STATUS": "ACCEPT", "NUM": len(existing.get("acked", [])), "REQUEST_ID": req_id})
                            continue

                        # select available workers
                        selected = []
                        with self.workers_lock:
                            for w_uuid, info in list(self.workers.items()):
                                if not info.get("busy") and not info.get("borrowed_from") and not info.get("borrowed_pending"):
                                    selected.append(w_uuid)
                                    if len(selected) >= num:
                                        break
                        if not selected:
                            self._send_line(conn, {"TASK": "BORROW_RESPONSE", "STATUS": "REJECT", "NUM": 0})
                            continue

                        with self.pending_lock:
                            self.pending_borrows[req_id] = {"from": from_uuid, "host": from_host, "port": from_port, "target": selected.copy(), "acked": [], "timestamp": time.time(), "attempts": 0}

                        acked = []
                        for w_uuid in selected:
                            with self.workers_lock:
                                info = self.workers.get(w_uuid)
                            if not info:
                                continue
                            try:
                                info["borrowed_pending"] = from_uuid
                                if info.get("protocol") == "sprint2":
                                    command = {
                                        "type": "command_redirect",
                                        "request_id": req_id,
                                        "payload": {
                                            "new_master_address": f"{from_host}:{from_port}",
                                            "original_master_address": f"{self.host}:{self.port}"
                                        }
                                    }
                                    ok = self._send_text(info["conn"], json.dumps(command))
                                else:
                                    instruct = {"TASK": "TRANSFER_INSTRUCT", "HOST": from_host, "PORT": from_port, "REQUEST_ID": req_id}
                                    ok = self._send_line(info["conn"], instruct)
                                if ok:
                                    acked.append(w_uuid)
                                    with self.borrowed_lock:
                                        self.workers_borrowed[w_uuid] = {
                                            "original_master_host": self.host,
                                            "original_master_port": self.port,
                                            "borrowed_from_host": from_host,
                                            "borrowed_from_port": from_port,
                                            "borrowed_from_uuid": from_uuid
                                        }
                                else:
                                    info.pop("borrowed_pending", None)
                            except Exception:
                                info.pop("borrowed_pending", None)

                        with self.pending_lock:
                            rec = self.pending_borrows.get(req_id)
                            if rec is not None:
                                rec["acked"] = acked

                        self._send_line(conn, {"TASK": "BORROW_RESPONSE", "STATUS": "ACCEPT", "NUM": len(acked), "REQUEST_ID": req_id})
                        continue

                    elif task == "TRANSFER_COMPLETE":
                        w_uuid = payload.get("WORKER_UUID")
                        req_id_p = payload.get("REQUEST_ID")
                        with self.pending_lock:
                            pending = self.pending_borrows.get(req_id_p)
                            if pending and w_uuid in pending.get("acked", []):
                                pending["acked"].remove(w_uuid)
                                if not pending["acked"] and not pending.get("target", []):
                                    self.pending_borrows.pop(req_id_p, None)
                        with self.workers_lock:
                            if w_uuid in self.workers:
                                self.workers.pop(w_uuid, None)
                        try:
                            self._send_line(conn, {"TASK": "ACK", "STATUS": "TRANSFERED", "WORKER_UUID": w_uuid, "REQUEST_ID": req_id_p})
                        except Exception:
                            pass
                        continue

                    elif task == "BORROW_RESULT":
                        # Received a result/notification about a borrow request (from a peer master)
                        peer_host = payload.get("PEER_HOST")
                        peer_port = int(payload.get("PEER_PORT")) if payload.get("PEER_PORT") else None
                        # set a local cooldown to avoid immediate re-requesting this peer
                        if peer_host and peer_port:
                            self.borrow_cooldowns[(peer_host, peer_port)] = time.time()
                            print(f"[BORROW-RESULT] Received BORROW_RESULT from {addr} — setting cooldown for {peer_host}:{peer_port}")
                        continue

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
                    info = self.workers.get(worker_uuid)
                    if info and info.get("borrowed_pending"):
                        # Keep the worker record during pending transfer, but clear live conn
                        info["conn"] = None
                        info["addr"] = None
                        print(f"[UNREGISTERED] Master {self.port} marked worker {worker_uuid} disconnected (borrowed_pending kept) — total={len(self.workers)}")
                    else:
                        self.workers.pop(worker_uuid, None)
                        print(f"[UNREGISTERED] Master {self.port} removed worker {worker_uuid} — total={len(self.workers)}")
            try:
                conn_file.close()
            except Exception:
                pass
            conn.close()
            print(f"[CONEXÃO] Worker {worker_uuid or addr} desconectado")

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

    def _dispatch_idle_workers(self):
        with self.workers_lock:
            idle_workers = [
                (w_uuid, info)
                for w_uuid, info in self.workers.items()
                if not info.get("busy") and info.get("conn") and info.get("protocol", "legacy") == "legacy"
            ]
            if not idle_workers:
                return

            start = self.next_worker_index % len(idle_workers)
            ordered_idle = idle_workers[start:] + idle_workers[:start]

            for w_uuid, info in ordered_idle:
                try:
                    task = self.task_queue.get_nowait()
                except queue.Empty:
                    break

                try:
                    self._send(info["conn"], task)
                    info["busy"] = True
                    print(f"[DISPATCH] Tarefa enviada a {w_uuid}: USER={task.get('USER')}")
                    self.next_worker_index = (self.next_worker_index + 1) % len(self.workers) if self.workers else 0
                except Exception as e:
                    print(f"[DISPATCH-ERR] Falha ao enviar a {w_uuid}: {e}")
                    self.task_queue.put(task)
                    break

    def _monitor_saturation(self):
        while self.running:
            load = self.task_queue.qsize()
            if load >= THRESHOLD:
                print(f"\n[⚠ SATURAÇÃO] Fila={load} ≥ Threshold={THRESHOLD}")
                if self.master_peers:
                    for peer in self.master_peers:
                        try:
                            host, port = peer
                            # avoid spamming request_help to same peer within TTL
                            last = self.borrow_cooldowns.get((host, port))
                            if last and time.time() - last < PENDING_TTL:
                                continue

                            got = self.request_borrow(host, port, 1)
                            # set cooldown to avoid immediate repeated requests
                            self.borrow_cooldowns[(host, port)] = time.time()
                            if got:
                                print(f"[REQUEST_HELP] Recebido {got} workers de {host}:{port}")
                                break
                        except Exception as e:
                            print(f"[REQUEST_HELP-ERR] falha ao contatar {peer}: {e}")
            time.sleep(5)

    def _dispatch_loop(self):
        while self.running:
            self._dispatch_idle_workers()
            time.sleep(0.5)

    def _release_saturation_loop(self):
        """Monitora quando a carga normaliza e libera workers emprestados (command_release - Sprint 3)."""
        while self.running:
            load = self.task_queue.qsize()
            
            # Liberar workers quando carga < RELEASE_THRESHOLD (histerese para evitar oscilações)
            if load < RELEASE_THRESHOLD:
                to_release = []
                with self.borrowed_lock:
                    for w_uuid, borrow_info in list(self.workers_borrowed.items()):
                        to_release.append((w_uuid, borrow_info))
                
                for w_uuid, borrow_info in to_release:
                    with self.workers_lock:
                        winfo = self.workers.get(w_uuid)
                    
                    if winfo and winfo.get("conn"):
                        # Enviar COMMAND_RELEASE conforme Sprint 3, seção 2.5.a
                        orig_host = borrow_info.get("original_master_host")
                        orig_port = borrow_info.get("original_master_port")
                        
                        command = {
                            "type": "command_release",
                            "request_id": f"{self.port}-{int(time.time()*1000)}",
                            "payload": {
                                "original_master_address": f"{orig_host}:{orig_port}"
                            }
                        }
                        
                        try:
                            if self._send_line(winfo["conn"], command):
                                print(f"[RELEASE] Enviado COMMAND_RELEASE a {w_uuid} → {orig_host}:{orig_port}")
                                
                                # Remover do registro de workers
                                with self.workers_lock:
                                    self.workers.pop(w_uuid, None)
                                with self.borrowed_lock:
                                    self.workers_borrowed.pop(w_uuid, None)
                                
                                # Enviar notify_worker_returned conforme Sprint 3, seção 2.5.b
                                self._notify_worker_returned(w_uuid, orig_host, orig_port, borrow_info)
                            else:
                                print(f"[RELEASE-ERR] Falha ao enviar COMMAND_RELEASE a {w_uuid}")
                        except Exception as e:
                            print(f"[RELEASE-ERR] {w_uuid}: {e}")
            
            time.sleep(3)  # Verificar a cada 3 segundos

    def _notify_worker_returned(self, worker_id: str, orig_host: str, orig_port: int, borrow_info: dict):
        """Notifica o master original que um worker emprestado foi devolvido (notify_worker_returned - Sprint 3)."""
        try:
            notification = {
                "type": "notify_worker_returned",
                "request_id": f"{self.port}-{int(time.time()*1000)}",
                "payload": {
                    "worker_id": worker_id,
                    "original_master_address": f"{orig_host}:{orig_port}"
                }
            }
            
            with socket.create_connection((orig_host, orig_port), timeout=COMMAND_RELEASE_TIMEOUT) as s:
                s.sendall((json.dumps(notification) + "\n").encode())
                print(f"[NOTIFY] Worker {worker_id} devolvido a {orig_host}:{orig_port}")
        except Exception as e:
            print(f"[NOTIFY-ERR] Falha ao notificar {orig_host}:{orig_port}: {e}")

    def start(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(20)
        self.server_sock.settimeout(1)

        self._setup_udp_socket()
        threading.Thread(target=self._master_udp_listener, daemon=True).start()
        threading.Thread(target=self._master_discovery_loop, daemon=True).start()
        threading.Thread(target=self._dispatch_loop, daemon=True).start()
        threading.Thread(target=self._monitor_saturation, daemon=True).start()
        threading.Thread(target=self._release_saturation_loop, daemon=True).start()
        threading.Thread(target=self._pending_cleanup_loop, daemon=True).start()

        print(f"\n{'═'*55}")
        print(f"  MASTER [{MASTER_UUID}] ONLINE — {self.host}:{self.port}")
        print(f"  Threshold de saturação: {THRESHOLD} tarefas")
        print(f"{'═'*55}\n")

        while self.running:
            try:
                conn, addr = self.server_sock.accept()
                threading.Thread(target=self.handle_worker, args=(conn, addr), daemon=True).start()
            except socket.timeout:
                continue

    def request_borrow(self, host: str, port: int, num: int = 1, timeout: int = 5) -> int:
        retries = 3
        req_id = str(uuid.uuid4())
        attempt = 0
        while attempt < retries:
            attempt += 1
            try:
                with socket.create_connection((host, port), timeout=timeout) as s:
                    payload = {
                        "type": "request_help",
                        "request_id": req_id,
                        "payload": {
                            "master_id": MASTER_UUID,
                            "current_load": self.task_queue.qsize(),
                            "capacity": CAPACITY,
                            "workers_needed": num,
                            "host": self.host,
                            "port": self.port
                        }
                    }
                    s.sendall((json.dumps(payload) + "\n").encode())
                    buf = b""
                    s.settimeout(timeout)
                    while b"\n" not in buf:
                        chunk = s.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                    if b"\n" in buf:
                        line, _ = buf.split(b"\n", 1)
                        resp = json.loads(line.decode())
                        # Sprint3 responses use "type": "response_accepted" / "response_rejected"
                        rtype = str(resp.get("type", "")).lower()
                        if rtype == "response_accepted":
                            return int(resp.get("payload", {}).get("workers_offered", 0))
                        if rtype == "response_rejected":
                            return 0
                        # Backwards-compatible legacy borrow response
                        task_type = str(resp.get("TASK", "")).upper()
                        if task_type == "BORROW_RESPONSE" and resp.get("STATUS") == "ACCEPT":
                            return int(resp.get("NUM", 0))
            except Exception as e:
                print(f"[REQUEST_HELP-ERR] {e}")
                time.sleep(1 + attempt)
        return 0

    def _pending_cleanup_loop(self):
        while self.running:
            now = time.time()
            expired = []
            with self.pending_lock:
                for req_id, info in list(self.pending_borrows.items()):
                    target = info.get("target", [])
                    acked = info.get("acked", [])
                    remaining = [w for w in target if w not in acked]
                    if remaining and info.get("attempts", 0) < MAX_INSTRUCT_RETRIES:
                        info["attempts"] = info.get("attempts", 0) + 1
                        info["timestamp"] = now
                        for w_uuid in remaining:
                            with self.workers_lock:
                                winfo = self.workers.get(w_uuid)
                            if not winfo:
                                continue
                            try:
                                instruct = {"TASK": "TRANSFER_INSTRUCT", "HOST": info.get("host"), "PORT": info.get("port"), "REQUEST_ID": req_id}
                                ok = self._send_line(winfo["conn"], instruct)
                                if ok:
                                    with self.pending_lock:
                                        rec = self.pending_borrows.get(req_id)
                                        if rec is not None:
                                            rec.setdefault("acked", []).append(w_uuid)
                                            with self.workers_lock:
                                                if w_uuid in self.workers:
                                                    self.workers[w_uuid]["borrowed_pending"] = info.get("from")
                                            print(f"[BORROW-RETRY] Re-instruído worker {w_uuid} para {info.get('host')}:{info.get('port')}")
                            except Exception as e:
                                print(f"[BORROW-RETRY-ERR] {w_uuid}: {e}")
                    elif info.get("attempts", 0) >= MAX_INSTRUCT_RETRIES or now - info.get("timestamp", 0) > PENDING_TTL:
                        expired.append((req_id, info))

            for req_id, info in expired:
                target = info.get("target", [])
                acked = info.get("acked", [])
                print(f"[PENDING-EXPIRE] Request {req_id} expired — rolling back {len(acked)} acked workers")
                with self.workers_lock:
                    for w_uuid in list(acked):
                        winfo = self.workers.get(w_uuid)
                        if winfo and winfo.get("borrowed_pending"):
                            winfo.pop("borrowed_pending", None)
                            print(f"[PENDING-ROLLBACK] Worker {w_uuid} unmarked borrowed_pending")

                try:
                    host = info.get("host")
                    port = info.get("port")
                    result = {"TASK": "BORROW_RESULT", "REQUEST_ID": req_id, "STATUS": "EXPIRED", "ACKED": len(acked), "TARGET": len(target), "PEER_HOST": self.host, "PEER_PORT": self.port}
                    with socket.create_connection((host, port), timeout=3) as s:
                        s.sendall((json.dumps(result) + "\n").encode())
                except Exception:
                    pass

                with self.pending_lock:
                    self.pending_borrows.pop(req_id, None)

            time.sleep(2)

    def shutdown(self):
        print(f"\n[MASTER] Encerrando {MASTER_UUID}...")
        self.running = False
        try:
            self.server_sock.close()
        except:
            pass


master = None


def signal_handler(sig, frame):
    if master:
        master.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Master node for P2P cluster")
    parser.add_argument("--host", default=HOST, help="Master host/address to bind to")
    parser.add_argument("--port", type=int, default=PORT, help="Master port to bind to")
    parser.add_argument("--uuid", default=MASTER_UUID, help="Master UUID identifier (e.g., Master_11)")
    parser.add_argument("--peers", default="", help="Comma-separated list of peer masters (host:port,host:port)")
    parser.add_argument("--fixed-partner-peers", action="store_true", help="Use fixed partner master peers 10.62.206.21 and 10.62.206.31")
    args = parser.parse_args()

    # Configurar UUID do Master
    MASTER_UUID = args.uuid
    
    # Configurar peers (masters other than this one for borrow/lending)
    if args.fixed_partner_peers:
        MASTER_PEERS = list(FIXED_PARTNER_PEERS)
        print(f"[PEERS] Usando fixed partner peers: {MASTER_PEERS}")
    elif args.peers:
        MASTER_PEERS = [tuple(peer.strip().split(":")) for peer in args.peers.split(",")]
        MASTER_PEERS = [(host, int(port)) for host, port in MASTER_PEERS]
    else:
        MASTER_PEERS = []

    master = MasterNode(host=args.host, port=args.port)
    signal.signal(signal.SIGINT, signal_handler)
    try:
        master.start()
    finally:
        print("[MASTER] Finalizado")
