import threading
import time
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


def test_borrow_worker_flow():
    # use ephemeral ports to avoid collisions when tests run together
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

    # start two workers: one for each master
    w1 = WorkerNode(port=_free_port())
    w2 = WorkerNode(port=_free_port())
    # point workers to the dynamic masters
    w1.master_host = "127.0.0.1"
    w1.master_port = p1
    w2.master_host = "127.0.0.1"
    w2.master_port = p2

    start_worker_in_thread(w1)
    start_worker_in_thread(w2)

    # wait for registrations
    deadline = time.time() + 5
    while time.time() < deadline:
        if len(m1.workers) + len(m2.workers) >= 2:
            break
        time.sleep(0.2)

    assert len(m1.workers) + len(m2.workers) >= 2

    # force saturation on m1
    for i in range(master_mod.THRESHOLD + 2):
        m1.task_queue.put({"TASK": "QUERY", "USER": f"U{i}"})

    # allow monitor to run and request borrow
    time.sleep(6)

    # wait up to 10s for worker transfer: m1 should have increased workers OR m2 decreased
    deadline = time.time() + 10
    transferred = False
    while time.time() < deadline:
        if len(m1.workers) >= 1 and len(m2.workers) < 2:
            transferred = True
            break
        time.sleep(0.5)

    assert transferred, f"Expected a worker transfer but state m1:{len(m1.workers)} m2:{len(m2.workers)}"
    # check log file persisted
    import os
    import time as _time
    _time.sleep(0.5)
    assert os.path.exists(master_mod.LOG_FILE)
    with open(master_mod.LOG_FILE, 'r', encoding='utf-8') as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
    assert len(lines) > 0
