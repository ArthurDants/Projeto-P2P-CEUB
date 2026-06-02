#!/bin/bash
# Test script to verify Master 11 with 2 Workers and criteria compliance

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Teste - Master 11 com 2 Workers (Sem Carga)${NC}"
echo -e "${BLUE}================================================${NC}\n"

# Kill any existing processes on ports
echo -e "${YELLOW}[*] Limpando portas anteriores...${NC}"
lsof -ti:5000 | xargs kill -9 2>/dev/null || true
lsof -ti:5002 | xargs kill -9 2>/dev/null || true
lsof -ti:5003 | xargs kill -9 2>/dev/null || true
lsof -ti:5004 | xargs kill -9 2>/dev/null || true
sleep 1

echo -e "${BLUE}[1] Iniciando Master 11 na porta 5000...${NC}"
python master.py --host 127.0.0.1 --port 5000 --uuid "Master_11" &
MASTER_PID=$!
sleep 2

echo -e "${BLUE}[2] Iniciando Worker 1 na porta 5003...${NC}"
python worker.py --port 5003 --master-host 127.0.0.1 --master-port 5000 &
WORKER1_PID=$!
sleep 2

echo -e "${BLUE}[3] Iniciando Worker 2 na porta 5004...${NC}"
python worker.py --port 5004 --master-host 127.0.0.1 --master-port 5000 &
WORKER2_PID=$!
sleep 2

echo -e "${GREEN}✓ Cluster iniciado!${NC}"
echo -e "  Master 11 PID: $MASTER_PID"
echo -e "  Worker 1 PID: $WORKER1_PID"
echo -e "  Worker 2 PID: $WORKER2_PID\n"

echo -e "${YELLOW}================================================${NC}"
echo -e "${YELLOW}Status Esperado:${NC}"
echo -e "  • Master 11 ONLINE na porta 5000"
echo -e "  • 2 Workers conectados e OCIOSOS (sem carga)"
echo -e "  • Tarefas geradas a cada 4 segundos"
echo -e "  • Fila com até 5 tarefas antes de solicitar ajuda"
echo -e "${YELLOW}================================================\n${NC}"

echo -e "${BLUE}Pressione Ctrl+C para encerrar tudo${NC}\n"

# Wait for all processes
wait $MASTER_PID $WORKER1_PID $WORKER2_PID 2>/dev/null

# Cleanup
echo -e "\n${YELLOW}[*] Encerrando...${NC}"
kill $MASTER_PID $WORKER1_PID $WORKER2_PID 2>/dev/null || true
sleep 1
echo -e "${GREEN}✓ Finalizado${NC}"
