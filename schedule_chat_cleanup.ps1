# ============================================================
# AGENT NARADA - schedule the automatic chat-history cleanup
#
# Creates a Windows Task Scheduler task that runs
#     python manage.py delete_old_chats
# every hour, so chat messages older than 7 days are deleted even if
# nobody opens Agent Narada.
#
# Run it once, from the NARADA folder:
#     powershell -ExecutionPolicy Bypass -File schedule_chat_cleanup.ps1
#
# Running it again simply replaces the task (safe to repeat).
# To remove the task:
#     Unregister-ScheduledTask -TaskName "Agent Narada - delete old chats" -Confirm:$false
# ============================================================

$ErrorActionPreference = "Stop"   # stop at the first error instead of carrying on

$TaskName = "Agent Narada - delete old chats"

# Paths are worked out from where this file is, so the project folder
# can be anywhere.
$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend"
# pythonw.exe is Python without a console window, so nothing pops up
# on the screen every hour.
$Python = Join-Path $Root ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment not found at $Python. Run 'python main.py' once first."
}

# WHAT to run: the cleanup command, inside the backend folder.
$Action = New-ScheduledTaskAction -Execute $Python -Argument "manage.py delete_old_chats" -WorkingDirectory $Backend

# WHEN: starting in one minute, then every hour, with no end date.
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Hours 1)

# HOW:
#   -StartWhenAvailable        if the laptop was off or asleep at a run time,
#                              run as soon as it is back on
#   -AllowStartIfOnBatteries / -DontStopIfGoingOnBatteries
#                              a laptop on battery still runs it
#   -ExecutionTimeLimit        stop it if it ever takes over 10 minutes
#   -MultipleInstances         never run two cleanups at the same time
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Deletes Agent Narada chat messages older than 7 days (manage.py delete_old_chats)." `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Force | Out-Null

Write-Host "Scheduled task created: $TaskName"
Write-Host "It runs every hour. Check it in Task Scheduler (taskschd.msc), or with:"
Write-Host "    Get-ScheduledTaskInfo -TaskName '$TaskName'"
