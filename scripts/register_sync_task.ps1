<#
.SYNOPSIS
    Registers the 6DE Excel -> platform sync as a Windows Scheduled Task.

.DESCRIPTION
    Runs scripts/sync_all.py every 30 minutes so the platform mirrors the
    OneDrive workbooks without anyone remembering to do it.

    JUAN RUNS THIS ONCE. The AI never registers scheduled tasks itself — a
    background job that survives reboots and writes to the production database
    is exactly the kind of persistence a person should switch on deliberately.

    What the task actually does is safe by construction:
      - reads the workbooks (never writes to them, never even opens them for
        write — each is copied to a temp file first),
      - skips entirely when a workbook has not changed,
      - reconciles BEFORE writing and refuses to import anything whose totals
        do not match the workbook's own control figure,
      - logs every run to db/sync_runs.jsonl and records freshness in the
        database, which the app shows on /Health.

.PARAMETER IntervalMinutes
    How often to run. Default 30.

.PARAMETER DryRun
    Register the task WITHOUT --commit, so it only ever reports what it would
    do. Good for a first day of watching it before letting it write.

.PARAMETER Remove
    Unregister the task and exit.

.EXAMPLE
    # See what it would do, without writing to the database, for a day:
    .\scripts\register_sync_task.ps1 -DryRun

.EXAMPLE
    # The real thing, every 30 minutes:
    .\scripts\register_sync_task.ps1

.EXAMPLE
    .\scripts\register_sync_task.ps1 -Remove
#>
[CmdletBinding()]
param(
    [int]$IntervalMinutes = 30,
    [switch]$DryRun,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$TaskName = '6DE Platform Sync'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python   = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Script   = Join-Path $RepoRoot 'scripts\sync_all.py'

if ($Remove) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Green
    } catch {
        Write-Host "No scheduled task named '$TaskName' was registered." -ForegroundColor Yellow
    }
    exit 0
}

# Fail early and clearly rather than registering a task that can never run.
if (-not (Test-Path $Python)) {
    throw "Python not found at $Python. Create the virtualenv first (see README)."
}
if (-not (Test-Path $Script)) {
    throw "sync_all.py not found at $Script."
}

$Arguments = "`"$Script`""
if (-not $DryRun) { $Arguments += ' --commit' }

$Action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $RepoRoot

# Repeat indefinitely, starting a few minutes out so registering it does not
# immediately fire while you are still reading the output.
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(3) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

# Only when logged on and on a real session: the workbooks live in OneDrive
# under this user's profile, so the task cannot see them as SYSTEM.
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew        # never let two syncs overlap

try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop } catch {}

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings `
    -Description 'Syncs the 6DE OneDrive workbooks into the platform database. One-way, reconciled before every write.' | Out-Null

$mode = if ($DryRun) { 'DRY-RUN (reports only, writes nothing)' } else { 'COMMIT (writes reconciled data)' }
Write-Host ""
Write-Host "Registered '$TaskName'" -ForegroundColor Green
Write-Host "  mode     : $mode"
Write-Host "  every    : $IntervalMinutes minutes"
Write-Host "  runs as  : $env:USERNAME (only while logged on - OneDrive lives in your profile)"
Write-Host "  log      : $(Join-Path $RepoRoot 'db\sync_runs.jsonl')"
Write-Host ""
Write-Host "Check it in Task Scheduler, or run once now with:" -ForegroundColor Cyan
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove it with:" -ForegroundColor Cyan
Write-Host "  .\scripts\register_sync_task.ps1 -Remove"
