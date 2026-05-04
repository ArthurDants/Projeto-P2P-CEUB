import subprocess
import time
import sys
import os
import signal

def start_worker(port):
    return subprocess.Popen([sys.executable, "worker.py", str(port)])

if __name__ == "__main__":
    print("=== Iniciando Simulação de Cluster P2P ===")
    workers = []
    
    # Inicia 3 Workers em portas diferentes
    for i in range(3):
        port = 5003 + i
        print(f"Subindo Worker na porta {port}...")
        workers.append(start_worker(port))
        time.sleep(1)

    print("\nCluster rodando. Pressione Ctrl+C para encerrar.\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nEncerrando simulação...")
        for w in workers:
            w.terminate()
        print("Simulação finalizada.")
