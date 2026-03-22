import socket  
import json    
import threading 
import sys     

class MasterNode: # Define a classe que representa o Nó Master (servidor central)
    def __init__(self, host='0.0.0.0', port=5005): 
        self.host = host 
        self.port = port 
        self.server_uuid = "MASTER-001" 
        self.running = True 

    def handle_worker(self, conn, addr): # Função que gerencia a conversa com cada Worker individualmente
        print(f"\n[CONEXÃO] Worker em {addr} conectado.") 
        try: 
            conn.settimeout(10) 
            while self.running: 
                data = conn.recv(1024).decode('utf-8') 
                if not data: break 
                
                payload = json.loads(data.strip()) 
                
                if payload.get("TASK") == "HEARTBEAT": 
                    print(f"[HEARTBEAT] Worker {payload.get('SERVER_UUID')} está ativo.") 
                    
                    response = { # Monta o dicionário de resposta conforme o Payload Oficial
                        "SERVER_UUID": self.server_uuid, 
                        "TASK": "HEARTBEAT",             
                        "RESPONSE": "ALIVE"              
                    }
                    
                    conn.sendall((json.dumps(response) + "\n").encode('utf-8'))
        except Exception as e: # Captura erros como queda de conexão ou JSON inválido
            print(f"\n[AVISO] Conexão com {addr} encerrada: {e}") # Exibe o motivo da desconexão
        finally: 
            conn.close() 

    def start(self): # Função que inicia o servidor para receber conexões
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # Cria o socket IPv4 e TCP
        
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port)) 
        server.listen() 
        server.settimeout(1.0) 
        
        print(f"--- MASTER ONLINE EM {self.host}:{self.port} ---") 
        print("Pressione Ctrl+C para encerrar o servidor com segurança.\n") 
        
        try: # Bloco para capturar a interrupção de teclado (Ctrl+C)
            while self.running: 
                try: 
                    conn, addr = server.accept() 
                    thread = threading.Thread(target=self.handle_worker, args=(conn, addr), daemon=True)
                    thread.start() 
                except socket.timeout: 
                    continue 
        except KeyboardInterrupt: # Executa quando o usuário aperta Ctrl+C
            print("\n[ENCERRANDO] Master desligando pelo usuário...") 
        finally: 
            self.running = False 
            server.close() 
            sys.exit(0) 

if __name__ == "__main__": 
    master = MasterNode() 
    master.start() 
