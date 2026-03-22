import socket
import json
import time

class WorkerNode:
    def __init__(self, master_host='10.62.206.35', master_port=5000):
        self.master_host = master_host
        self.master_port = master_port

    def send_heartbeat(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.master_host, self.master_port))
                
                while True:
                    payload = {
                        "SERVER_UUID": "WORKER-A2", 
                        "TASK": "HEARTBEAT"
                    }
                  
                    message = json.dumps(payload) + "\n"
                    s.sendall(message.encode('utf-8'))
                    print(f"[WORKER] Heartbeat enviado...")
                    data = s.recv(1024).decode('utf-8')
                    if data:
                        response = json.loads(data.strip())
                        print(f"[WORKER] Resposta do Master: {response.get('RESPONSE')}")
                    
                    time.sleep(5)
        except Exception as e:
            print(f"[ERRO] Não foi possível conectar ao Master: {e}")

if __name__ == "__main__":
    worker = WorkerNode()
    worker.send_heartbeat()
