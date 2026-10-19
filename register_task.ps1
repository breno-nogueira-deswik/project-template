<#
.SYNOPSIS
    Cria, atualiza ou remove a tarefa no Agendador do Windows que roda o main.py
    do projeto sem janela (pythonw.exe).

.DESCRIPTION
    Generico para qualquer projeto do template: tudo e resolvido a partir da pasta
    onde este script esta (raiz do projeto). Por padrao o nome da tarefa e o nome
    da pasta do projeto.

    Pre-requisitos:
      - .venv criado na raiz do projeto com as dependencias instaladas
        (python -m venv .venv ; .venv\Scripts\pip install -r requirements.txt)
      - .env preenchido (tokens)
    Rode a partir da pasta LOCAL do projeto (ex.: C:\Scripts PMO\<projeto>), nao por
    um caminho de rede: o Agendador pode nao ter acesso a rede no horario da tarefa.

    Rodar a tarefa de novo com o mesmo nome a sobrescreve (atualiza horarios etc.).

.EXAMPLE
    # Teste: roda so com o usuario logado, todo dia as 08:00
    .\register_task.ps1

.EXAMPLE
    # VM: roda mesmo sem ninguem logado (pede a senha do usuario)
    .\register_task.ps1 -Mode Password -Times '07:00','13:00'

.EXAMPLE
    # So em dias uteis
    .\register_task.ps1 -Mode Password -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday

.EXAMPLE
    # Remover a tarefa
    .\register_task.ps1 -Remove
#>
param(
    # Interactive = so com o usuario logado; Password = mesmo sem sessao aberta
    [ValidateSet('Interactive', 'Password')]
    [string]$Mode = 'Interactive',

    # Padrao: nome da pasta do projeto
    [string]$TaskName = (Split-Path $PSScriptRoot -Leaf),

    # Horarios no formato HH:mm (um gatilho por horario)
    [string[]]$Times = @('08:00'),

    # Vazio = todo dia; senao, so nos dias informados
    [ValidateSet('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')]
    [string[]]$DaysOfWeek = @(),

    # Tempo maximo de execucao; passou disso, o Agendador encerra o processo
    [int]$TimeLimitMinutes = 30,

    # Script e venv, relativos a raiz do projeto
    [string]$Script = 'main.py',
    [string]$VenvDir = '.venv',

    # Remove a tarefa em vez de criar
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

# -- Remocao ------------------------------------------------------------------
if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Tarefa '$TaskName' removida."
    } else {
        Write-Host "Tarefa '$TaskName' nao existe."
    }
    return
}

# -- Validacoes ---------------------------------------------------------------
if ($PSScriptRoot.StartsWith('\\')) {
    throw "Rode a partir de uma pasta local, nao de um caminho de rede ($PSScriptRoot)."
}

$horarios = foreach ($t in $Times) {
    try { [datetime]::ParseExact($t, 'HH:mm', $null) }
    catch { throw "Horario invalido '$t' (use HH:mm, ex.: 08:00)." }
}

# pythonw.exe = Python sem janela de console (a tarefa roda oculta e o exit code
# chega ao Agendador em 'Resultado da Ultima Execucao').
$pythonw = Join-Path $PSScriptRoot "$VenvDir\Scripts\pythonw.exe"
$scriptPath = Join-Path $PSScriptRoot $Script
if (-not (Test-Path $pythonw)) {
    throw "pythonw.exe nao encontrado em $pythonw (crie o $VenvDir, veja o README)."
}
if (-not (Test-Path $scriptPath)) {
    throw "Script nao encontrado: $scriptPath"
}
if (-not (Test-Path (Join-Path $PSScriptRoot '.env'))) {
    Write-Warning "Arquivo .env nao encontrado na raiz do projeto (tokens nao serao lidos)."
}

# -- Tarefa -------------------------------------------------------------------
# Um gatilho por horario: diario ou semanal nos dias informados
$trigger = @(foreach ($h in $horarios) {
    if ($DaysOfWeek.Count -gt 0) {
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DaysOfWeek -At $h
    } else {
        New-ScheduledTaskTrigger -Daily -At $h
    }
})

# WorkingDirectory = raiz do projeto (caminhos relativos e .env funcionam)
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$scriptPath`"" `
    -WorkingDirectory $PSScriptRoot

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes $TimeLimitMinutes) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$description = "Pipeline $TaskName ($Script). Log em " + (Join-Path $PSScriptRoot 'logs\pipeline_<data>.log')
$user = "$env:USERDOMAIN\$env:USERNAME"

if ($Mode -eq 'Interactive') {
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Description $description -Action $action `
        -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
} else {
    $cred = Get-Credential -UserName $user -Message "Senha de $user (a tarefa roda mesmo sem sessao aberta)"
    Register-ScheduledTask -TaskName $TaskName -Description $description -Action $action `
        -Trigger $trigger -Settings $settings -RunLevel Limited `
        -User $cred.UserName -Password $cred.GetNetworkCredential().Password -Force | Out-Null
}

$quando = if ($DaysOfWeek.Count -gt 0) { $DaysOfWeek -join ', ' } else { 'todo dia' }
Write-Host "Tarefa '$TaskName' registrada ($Mode) para $user."
Write-Host "Roda $quando as $($Times -join ', ')."
Write-Host "Testar agora:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Ver resultado: Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Host "Remover:       .\register_task.ps1 -Remove"
