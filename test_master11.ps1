# Test script for Master 11 with 2 Workers (Windows PowerShell)
# Verificar conformidade com os critérios de avaliação

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Teste - Master 11 com 2 Workers (Sem Carga)" -ForegroundColor Cyan
Write-Host "  Verificação dos Critérios de Avaliação" -ForegroundColor Cyan
Write-Host "================================================`n" -ForegroundColor Cyan

# Kill previous processes
Write-Host "[*] Limpando processos anteriores..." -ForegroundColor Yellow
Get-Process | Where-Object { $_.ProcessName -eq "python" -and $_.CommandLine -match "master|worker" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "`n[1] Iniciando Master 11 na porta 5000..." -ForegroundColor Cyan
$MasterProcess = Start-Process python -ArgumentList "master.py --host 127.0.0.1 --port 5000 --uuid `"Master_11`"" -PassThru -NoNewWindow
Start-Sleep -Seconds 3

Write-Host "[2] Iniciando Worker 1 na porta 5003..." -ForegroundColor Cyan
$Worker1Process = Start-Process python -ArgumentList "worker.py --port 5003 --master-host 127.0.0.1 --master-port 5000" -PassThru -NoNewWindow
Start-Sleep -Seconds 2

Write-Host "[3] Iniciando Worker 2 na porta 5004..." -ForegroundColor Cyan
$Worker2Process = Start-Process python -ArgumentList "worker.py --port 5004 --master-host 127.0.0.1 --master-port 5000" -PassThru -NoNewWindow
Start-Sleep -Seconds 2

Write-Host "`n" -ForegroundColor Green
Write-Host "SUCCESS - Cluster iniciado!" -ForegroundColor Green
Write-Host "  Master 11 PID: $($MasterProcess.Id)" -ForegroundColor Green
Write-Host "  Worker 1 PID: $($Worker1Process.Id)" -ForegroundColor Green
Write-Host "  Worker 2 PID: $($Worker2Process.Id)" -ForegroundColor Green

Write-Host "`n================================================" -ForegroundColor Yellow
Write-Host "Status Esperado:" -ForegroundColor Yellow
Write-Host "  ✓ Master 11 ONLINE na porta 5000" -ForegroundColor Green
Write-Host "  ✓ 2 Workers conectados e OCIOSOS (sem carga)" -ForegroundColor Green
Write-Host "  ✓ Tarefas geradas a cada 4 segundos (TASK_INTERVAL=4)" -ForegroundColor Green
Write-Host "  ✓ Fila com até 5 tarefas antes de solicitar ajuda (THRESHOLD=5)" -ForegroundColor Green
Write-Host "  ✓ Libera workers quando carga < 2 (RELEASE_THRESHOLD=2)" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Yellow

Write-Host "`nPressione Enter para encerrar..." -ForegroundColor Cyan
Read-Host

Write-Host "`n[*] Encerrando processos..." -ForegroundColor Yellow
$MasterProcess, $Worker1Process, $Worker2Process | ForEach-Object { 
    try { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue } catch { }
}
Start-Sleep -Seconds 1

Write-Host "SUCCESS - Cluster finalizado" -ForegroundColor Green
