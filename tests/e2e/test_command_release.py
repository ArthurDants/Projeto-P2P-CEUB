import threading
import time
import socket

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


def test_command_release_on_desaturation():
    """Teste Sprint 3, seção 2.5: Validar command_release e notify_worker_returned."""
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

    # start one worker attached to m2
    w = WorkerNode(port=_free_port())
    w.master_host = "127.0.0.1"
    w.master_port = p2
    start_worker_in_thread(w)

    # wait for registration
    deadline = time.time() + 5
    while time.time() < deadline:
        if len(m2.workers) >= 1:
            break
        time.sleep(0.2)

    assert len(m2.workers) >= 1, "Worker não registrado em M2"

    # saturate m1 so it requests borrow
    for i in range(master_mod.THRESHOLD + 2):
        m1.task_queue.put({"TASK": "QUERY", "USER": f"U{i}"})

    # allow monitor to run and request borrow
    time.sleep(6)

    # validate worker was borrowed
    assert len(m1.workers) >= 1, f"Worker não foi transferido para M1 (M1.workers={len(m1.workers)})"
    assert len(m1.workers_borrowed) >= 1, "Worker não foi registrado em workers_borrowed"

    borrowed_worker_id = list(m1.workers_borrowed.keys())[0]
    print(f"[TEST] Worker {borrowed_worker_id} emprestado para M1")

    # now drain the task queue to simulate desaturation
    while not m1.task_queue.empty():
        try:
            m1.task_queue.get_nowait()
        except:
            break

    print(f"[TEST] Fila drenada. Aguardando RELEASE_SATURATION monitor...")
    time.sleep(5)

    # wait for release process (should happen in _release_saturation_loop)
    deadline = time.time() + 10
    released = False
    while time.time() < deadline:
        # check if worker was removed from m1 and returned to m2
        with m1.workers_lock:
            m1_count = len(m1.workers)
        with m2.workers_lock:
            m2_count = len(m2.workers)
        
        print(f"[TEST] M1 workers: {m1_count}, M2 workers: {m2_count}")
        
        if m1_count == 0 and m2_count >= 1:
            released = True
            break
        time.sleep(1)

    assert released, f"Worker não foi liberado via COMMAND_RELEASE (M1.workers={len(m1.workers)}, M2.workers={len(m2.workers)})"
    assert len(m1.workers_borrowed) == 0, "Workers_borrowed não foi limpo após release"

    print(f"[TEST] ✓ COMMAND_RELEASE funcionou corretamente!")
    print(f"[TEST] ✓ Worker retornou a M2 após desaturação")
