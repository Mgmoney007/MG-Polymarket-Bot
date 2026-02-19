<#
.SYNOPSIS
    Installs a Windows Task Scheduler task that runs the Polymarket bot every 15 minutes.

.DESCRIPTION
    Run this script once from an Administrator PowerShell prompt.
    It creates a task named "MG-Polymarket-Bot" that triggers every 15 minutes
    and appends all output (stdout + stderr) to bot.log in the same directory.

.PARAMETER PythonPath
    Full path to the Python executable.
    Defaults to .\venv\Scripts\python.exe, then falls back to whatever
    'python' resolves to on the system PATH.

.EXAMPLE
    # Run as Administrator:
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\setup_taskscheduler.ps1

    # With a custom Python interpreter:
    .\setup_taskscheduler.ps1 -PythonPath "C:\Python312\python.exe"

.NOTES
    To remove the task later:
        Unregister-ScheduledTask -TaskName "MG-Polymarket-Bot" -Confirm:$false

    To check current status:
        Get-ScheduledTask -TaskName "MG-Polymarket-Bot"
        Get-ScheduledTaskInfo -TaskName "MG-Polymarket-Bot"
#>

param(
    [string]$PythonPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TaskName   = "MG-Polymarket-Bot"
$ScriptDir  = $PSScriptRoot
$BotScript  = Join-Path $ScriptDir "run_bot.py"
$LogFile    = Join-Path $ScriptDir "bot.log"

# --------------------------------------------------------------------------
# Resolve Python interpreter
# --------------------------------------------------------------------------
if ($PythonPath -eq "") {
    $VenvPython = Join-Path $ScriptDir "venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        $PythonPath = $VenvPython
    } else {
        $PythonPath = (Get-Command python -ErrorAction SilentlyContinue)?.Source
        if (-not $PythonPath) {
            Write-Error ("Could not find a Python interpreter.`n" +
                         "Either create a virtualenv at .\venv or pass -PythonPath explicitly.")
            exit 1
        }
    }
}

Write-Host "Python:     $PythonPath"
Write-Host "Bot script: $BotScript"
Write-Host "Log file:   $LogFile"
Write-Host ""

# --------------------------------------------------------------------------
# Check for existing task
# --------------------------------------------------------------------------
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Task '$TaskName' already exists. Removing it before re-creating..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# --------------------------------------------------------------------------
# Build the action
# Task Scheduler does not support I/O redirection directly, so we wrap the
# call in cmd.exe /c "..." >> log 2>&1  to get a persistent log file.
# --------------------------------------------------------------------------
$cmdArgs = "/c `"`"$PythonPath`" `"$BotScript`" >> `"$LogFile`" 2>&1`""

$Action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdArgs -WorkingDirectory $ScriptDir

# --------------------------------------------------------------------------
# Trigger: every 15 minutes, starting now, repeating indefinitely
# --------------------------------------------------------------------------
$StartTime  = (Get-Date).AddMinutes(1)   # start 1 minute from now
$RepeatSpan = New-TimeSpan -Minutes 15
$Duration   = ([TimeSpan]::MaxValue)     # run indefinitely

$Trigger = New-ScheduledTaskTrigger -Once `
    -At $StartTime `
    -RepetitionInterval $RepeatSpan `
    -RepetitionDuration $Duration

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries

# --------------------------------------------------------------------------
# Principal: run as the current user, only when logged in
# (avoids needing a password; suitable for interactive desktop use)
# --------------------------------------------------------------------------
$Principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

# --------------------------------------------------------------------------
# Register
# --------------------------------------------------------------------------
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $Action `
    -Trigger  $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "MG Polymarket paper trading bot - runs every 15 minutes" | Out-Null

Write-Host "Task '$TaskName' registered successfully."
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Check status : Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Host "  Run now      : Start-ScheduledTask  -TaskName '$TaskName'"
Write-Host "  Remove task  : Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host "  View log     : Get-Content '$LogFile' -Wait"
