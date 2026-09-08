#!/usr/bin/env pwsh
# ledger-history.ps1 - Windows port of ledger-history (session-group rotation).
#
# Groups the session-history subtree (agents/sessions.md, sessions/SUMMARY.md,
# sessions/<date-N>/) and rotates it memory/ -> history/ -> archive/ -> gc.
# Durable memory (user/, system/, decisions, backlog, flaws, inefficiencies)
# and collaboration events never rotate.
#
#   status                 current group, session count, zone sizes, due?
#   close [--milestone L] [--confirm]   consolidate the live group into
#                          history/group-<NNN>.md, start group NNN+1, roll the
#                          oldest readable group into archive/ when full.
#                          Prints the promotion checklist; only --confirm runs.
#   gc [--confirm]         delete oldest archive/ tarballs over the cap
#                          (git-recoverable). --confirm executes.
#
# Config: memory/workflows/history.conf - group_size=20, history_keep=3,
# archive_keep=12 (defaults when absent). Uses tar (Windows 10+ ships tar.exe)
# so archives are .tar.gz, matching the POSIX port.

[CmdletBinding()]
param(
  [Parameter(Position = 0)] [string] $Command = '',
  [Parameter(ValueFromRemainingArguments = $true)] [string[]] $RestArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say { param([string]$Message) Write-Output $Message }
function Die { param([string]$Message) [Console]::Error.WriteLine("ledger-history: $Message"); exit 2 }

$scriptDir = $PSScriptRoot
$coreDir = (Resolve-Path (Join-Path $scriptDir '..')).Path
$ledgerDir = Split-Path -Parent $coreDir
$memoryDir = Join-Path $ledgerDir 'memory'
$historyDir = Join-Path $ledgerDir 'history'
$archiveDir = Join-Path $ledgerDir 'archive'
$sessionsMd = Join-Path $memoryDir 'agents/sessions.md'
$summaryMd = Join-Path $memoryDir 'sessions/SUMMARY.md'
$rosterMd = Join-Path $memoryDir 'agents/roster.md'
$groupState = Join-Path $memoryDir 'agents/GROUP'
$configFile = Join-Path $memoryDir 'workflows/history.conf'

function Usage {
  @(
    'ledger-history - group and rotate session history',
    '  status                 current group, session count, zone sizes, due?',
    '  close [--milestone L] [--confirm]   close the live group into history/',
    '  gc [--confirm]         delete oldest archive/ tarballs over the cap',
    'Config: memory/workflows/history.conf (group_size, history_keep, archive_keep).'
  ) | ForEach-Object { Say $_ }
  exit 2
}

function Get-Conf { param([string]$Key, [int]$Default)
  if (Test-Path -LiteralPath $configFile) {
    foreach ($raw in Get-Content -LiteralPath $configFile) {
      $line = $raw.TrimEnd("`r")
      if ($line -match "^$Key=(\d+)\s*$") { return [int]$matches[1] }
    }
  }
  return $Default
}

function Get-GroupInt {
  if (Test-Path -LiteralPath $groupState) {
    foreach ($raw in Get-Content -LiteralPath $groupState) {
      $line = $raw.TrimEnd("`r")
      if ($line -match '^group=(\d+)') { return [int]$matches[1] }
    }
  }
  return 1
}

function Get-GroupOpened {
  if (Test-Path -LiteralPath $groupState) {
    foreach ($raw in Get-Content -LiteralPath $groupState) {
      $line = $raw.TrimEnd("`r")
      if ($line -match '^opened=(.*)$') { return $matches[1].Trim() }
    }
  }
  return ''
}

function Get-SessionCount {
  if (-not (Test-Path -LiteralPath $sessionsMd)) { return 0 }
  $n = 0
  foreach ($raw in Get-Content -LiteralPath $sessionsMd) {
    if ($raw -match '^## \d{4}-\d{2}-\d{2}.*Session ') { $n++ }
  }
  return $n
}

function Count-Archives { @(Get-ChildItem -LiteralPath $archiveDir -Filter 'group-*.tar.gz' -File -ErrorAction SilentlyContinue).Count }
function Count-History { @(Get-ChildItem -LiteralPath $historyDir -Filter 'group-*.md' -File -ErrorAction SilentlyContinue).Count }
function Today { (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd') }
function Pad { param([int]$N) '{0:000}' -f $N }

function Write-GroupState { param([int]$N, [string]$Opened)
  New-Item -ItemType Directory -Path (Split-Path -Parent $groupState) -Force | Out-Null
  @(
    '# Current session group - written by ledger-history. Do not hand-edit.',
    "group=$N",
    "opened=$Opened"
  ) -join "`n" | Set-Content -LiteralPath $groupState -NoNewline
}

function Reset-Registry {
  @(
    '# Agent Sessions (append-only within the current group)',
    '',
    'One entry per agent session in the CURRENT group, newest at the bottom.',
    'Closed groups live in .context_ledger/history/ and .context_ledger/archive/ (not read',
    'at session start). Rotate with ledger-history.',
    '',
    '<!-- TEMPLATE - copy below the last entry and FILL IN every placeholder:',
    '---',
    '## YYYY-MM-DD - Session N',
    '- **Agent:** <name> | **Model:** <model id> | **Platform:** <machine/sandbox + OS> | **Role:** <engineer, or overlay> | **Core:** <version>',
    '- **Task:** <what this session set out to do>',
    '- **Commits:** <count> (<first-sha>..<last-sha>)',
    '- **Outcome:** <done / partial / blocked>',
    '- **Open items:** <pointers into tasks/backlog.md, or "none">',
    '- **Notes:** .context_ledger/memory/sessions/<date>-<N>/notes.md  (or "none")',
    '-->'
  ) -join "`n" | Set-Content -LiteralPath $sessionsMd
}

function Reset-Summary {
  @(
    '# Session Summary (current group - prunable)',
    '',
    'One line per session: date, agent, model, one-line outcome. Closed groups',
    'are in .context_ledger/history/. Keep this small.'
  ) -join "`n" | Set-Content -LiteralPath $summaryMd
}

function Reset-Roster {
  if (-not (Test-Path -LiteralPath $rosterMd)) { return }
  @(
    '# Team Roster (current group - update in place)',
    '',
    'Pick a real name you like and add your row; present yourself by it',
    '("John (S<NNN>)"). Your name and codename are each unique in this group.',
    'The human is the supervisor. ledger-mem check flags a duplicate.',
    '',
    '<!-- TEMPLATE - one row per person in this group:',
    '| <Name> | S<NNN> | <model id> | <what you are doing> |',
    '-->',
    '',
    '| Name | Codename | Model | Doing |',
    '|------|----------|-------|-------|'
  ) -join "`n" | Set-Content -LiteralPath $rosterMd
}

function Show-PromotionChecklist {
  Say 'Before closing this group, confirm every open thread is captured in a'
  Say 'DURABLE file (it will NOT carry over implicitly - the new group starts clean):'
  Say '  - open work              -> tasks/backlog.md'
  Say '  - decisions in force      -> plans/decisions.md'
  Say '  - constraints/workarounds -> inefficiencies/log.md'
  Say '  - unresolved protocol traps -> flaws/log.md'
  Say '  - user preferences         -> user/preferences.md'
  Say 'Durable files persist across the boundary; the session stream resets.'
}

function Roll-OldestHistoryToArchive {
  $keep = Get-Conf 'history_keep' 3
  while ((Count-History) -gt $keep) {
    $oldest = Get-ChildItem -LiteralPath $historyDir -Filter 'group-*.md' -File | Sort-Object Name | Select-Object -First 1
    if (-not $oldest) { break }
    $base = [IO.Path]::GetFileNameWithoutExtension($oldest.Name)
    New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
    # tar runs with the CWD inside history/ and a relative -f path: GNU tar
    # (MSYS, often first on PATH) parses "C:\..." in -f as remote host "C"
    # and dies; bsdtar (System32 tar.exe) and GNU tar both accept a relative
    # name. archive/ is always a sibling of history/ under .context_ledger/.
    Push-Location $historyDir
    try {
      & tar -czf ("../{0}/{1}.tar.gz" -f (Split-Path -Leaf $archiveDir), $base) "$($oldest.Name)"
      if ($LASTEXITCODE -ne 0) { [Console]::Error.WriteLine("ledger-history: could not archive $base (need tar.exe)"); break }
      Remove-Item -LiteralPath $oldest.FullName -Force
      Say "archived $base -> archive/$base.tar.gz"
    } finally { Pop-Location }
  }
}

function Cmd-Status {
  $n = Pad (Get-GroupInt); $c = Get-SessionCount
  $gs = Get-Conf 'group_size' 20; $hk = Get-Conf 'history_keep' 3; $ak = Get-Conf 'archive_keep' 12
  $opened = Get-GroupOpened; if (-not $opened) { $opened = '-' }
  Say "Current group:   group-$n (opened $opened)"
  Say "Sessions in it:  $c / $gs"
  Say "history/:        $(Count-History) closed group(s) readable (keep $hk)"
  Say "archive/:        $(Count-Archives) tarball(s) (cap $ak)"
  if ($c -ge $gs) { Say ''; Say 'A close is DUE (>= group_size). Run: ledger-history close   (then --confirm)' }
  if ((Count-Archives) -gt $ak) { Say 'gc is DUE: archive/ over cap. Run: ledger-history gc --confirm' }
}

function Cmd-Close {
  $milestone = ''; $confirm = $false
  for ($i = 0; $i -lt $RestArgs.Count; $i++) {
    switch ($RestArgs[$i]) {
      '--milestone' { if ($i + 1 -ge $RestArgs.Count) { Die '--milestone needs a label' }; $milestone = $RestArgs[++$i] }
      '--confirm' { $confirm = $true }
      default { Die "unknown argument '$($RestArgs[$i])'" }
    }
  }
  if (-not (Test-Path -LiteralPath $sessionsMd)) { Die "no $sessionsMd - is this a bootstrapped project?" }
  $int = Get-GroupInt; $n = Pad $int; $next = Pad ($int + 1)
  $c = Get-SessionCount; $opened = Get-GroupOpened; if (-not $opened) { $opened = Today }
  $target = Join-Path $historyDir "group-$n.md"
  Say "== Closing group-$n =="
  Say "sessions: $c   opened: $opened   closing: $(Today)$(if ($milestone) { "   milestone: $milestone" })"
  Say ''; Show-PromotionChecklist; Say ''
  Say 'Plan:'
  Say "  - write $target (condensed registry + summaries)"
  Say "  - reset the live registry + SUMMARY for a new group-$next"
  Say '  - roll the oldest readable group into archive/ if history/ exceeds keep'
  if (-not $confirm) { Say ''; Say 'Dry run - nothing changed. Re-run with --confirm once promotion is done.'; return }

  New-Item -ItemType Directory -Path $historyDir -Force | Out-Null
  $lines = @("# Session group $n (closed $(Today))", '',
    "- Opened: $opened", "- Closed: $(Today)", "- Sessions: $c")
  if ($milestone) { $lines += "- Milestone: $milestone" }
  $lines += @('', 'Not read at session start - audit/lookback only.', '')
  if (Test-Path -LiteralPath $rosterMd) { $lines += @('## Team roster', ''); $lines += (Get-Content -LiteralPath $rosterMd); $lines += '' }
  $lines += @('## Session registry', '')
  $lines += (Get-Content -LiteralPath $sessionsMd)
  if (Test-Path -LiteralPath $summaryMd) { $lines += @('', '## Summaries', ''); $lines += (Get-Content -LiteralPath $summaryMd) }
  $lines -join "`n" | Set-Content -LiteralPath $target
  Say "wrote $target"

  Reset-Registry; Reset-Summary; Reset-Roster; Write-GroupState -N ($int + 1) -Opened (Today)
  Say "started group-$next"
  Roll-OldestHistoryToArchive
  Say ''; Say "Commit as: chore(ledger): close session group-$n, open group-$next"
}

function Cmd-Gc {
  $confirm = ($RestArgs -contains '--confirm')
  $ak = Get-Conf 'archive_keep' 12
  $tarballs = @(Get-ChildItem -LiteralPath $archiveDir -Filter 'group-*.tar.gz' -File -ErrorAction SilentlyContinue | Sort-Object Name)
  if ($tarballs.Count -le $ak) { Say "archive/ holds $($tarballs.Count) tarball(s), cap $ak - nothing to delete."; return }
  $over = $tarballs.Count - $ak
  $doomed = $tarballs | Select-Object -First $over
  Say "archive/ over cap ($($tarballs.Count) > $ak). Oldest-first, $over tarball(s) to delete:"
  $doomed | ForEach-Object { Say "  - $($_.Name)" }
  Say '(recoverable from git history after deletion - this only bounds the working tree)'
  if (-not $confirm) { Say 'Dry run - nothing deleted. Re-run with --confirm to delete.'; return }
  $doomed | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; Say "deleted $($_.Name)" }
  Say "Commit as: chore(ledger): gc archive/ to the $ak-tarball cap"
}

switch ($Command) {
  'status' { Cmd-Status; exit 0 }
  'close' { Cmd-Close; exit 0 }
  'gc' { Cmd-Gc; exit 0 }
  { $_ -in @('', '-h', '--help', 'help') } { Usage }
  default { Die "unknown command '$Command' (try: ledger-history.ps1 help)" }
}
