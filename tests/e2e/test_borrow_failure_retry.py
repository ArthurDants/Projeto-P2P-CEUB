import threading
import time
import socket
import json

import master as master_mod
from master import MasterNode
from worker import WorkerNode


def start_master_in_thread(master_instance):
    t = threading.Thread(target=master_instance.start, daemon=True)
    t.start()
    return t


def start_worker_in_thread(worker_instance):
    t = threading.Thread(target=worker_instance.start, daemon=True)
    t.start()
    return t


class BrokenWorker(WorkerNode):
    """Worker variant that ignores TRANSFER_INSTRUCT (doesn't send TRANSFER_COMPLETE)."""
    def _master_client_loop(self, host=None, port=None):
        # reuse base config but intercept TRANSFER_INSTRUCT
        host = host or self.master_host
        port = port or self.master_port
        while self.running:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(5)
                    s.connect((host, port))
                    s.settimeout(None)
                    presentation = {
                        "WORKER": "ALIVE",
                        "WORKER_UUID": self.worker_uuid,
                        "SERVER_UUID": None
                    }
                    self._send_line(s, presentation)

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
                            if task == "TRANSFER_INSTRUCT":
                                # simulate failure: close without sending TRANSFER_COMPLETE
                                self.log("Simulating transfer-failure: ignoring TRANSFER_INSTRUCT and closing connection")
                                return
                            # otherwise behave like normal minimal worker
                            if task == "QUERY":
                                time.sleep(0.1)
                                status = {"STATUS": "OK", "TASK": "QUERY", "WORKER_UUID": self.worker_uuid}
                                self._send_line(s, status)
            except Exception as e:
                self.log(f"Master connection (broken) error: {e}")
                time.sleep(1)


def test_borrow_failure_rolls_back():
    import socket
    def _free_port():
        s = socket.socket()
        s.bind(("", 0))
        p = s.getsockname()[1]
        s.close()
        return p

    p1 = _free_port()
    p2 = _free_port()
    master_mod.MASTER_PEERS = [("127.0.0.1", p1), ("127.0.0.1", p2)]

    m1 = MasterNode(host="127.0.0.1", port=p1)
    m2 = MasterNode(host="127.0.0.1", port=p2)

    start_master_in_thread(m1)
    start_master_in_thread(m2)

    time.sleep(0.5)

    # start one broken worker attached to m2
    w = BrokenWorker(port=_free_port())
    w.master_host = "127.0.0.1"
    w.master_port = p2
    start_worker_in_thread(w)

    # wait for registration
    deadline = time.time() + 5
    while time.time() < deadline:
        if len(m2.workers) >= 1:
            break
        time.sleep(0.2)

    assert len(m2.workers) >= 1

    # saturate m1 so it requests borrow
    for i in range(master_mod.THRESHOLD + 2):
        m1.task_queue.put({"TASK": "QUERY", "USER": f"U{i}"})

    # allow monitor to run and request borrow
    time.sleep(6)

    # ensure pending recorded initially
    assert any(m2.pending_borrows), "Expected pending_borrows entry in destination master"

    # wait longer than PENDING_TTL for rollback
    time.sleep(master_mod.PENDING_TTL + 4)

    # after expiration, pending_borrows should be cleared and worker still present in m2.workers
    assert not any(m2.pending_borrows), "Expected pending_borrows to be cleared after TTL"
    assert len(m2.workers) >= 1, "Expected worker to remain in origin master after rollback"
