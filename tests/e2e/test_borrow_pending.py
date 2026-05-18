import threading
import time

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


def test_pending_borrow_recorded():
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

    # one worker attached to m2
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

    assert len(m2.workers) >= 1

    # saturate m1 so it requests borrow
    for i in range(master_mod.THRESHOLD + 2):
        m1.task_queue.put({"TASK": "QUERY", "USER": f"U{i}"})

    # allow monitor to run and request borrow
    time.sleep(6)

    # verify m2 recorded a pending borrow (target list)
    assert any(info.get("target") for info in m2.pending_borrows.values()), "Expected pending_borrows entry in destination master"
