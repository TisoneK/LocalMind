#!/usr/bin/env pwsh
# context-mem.ps1 - Windows port of context-mem (memory-registry hygiene).
#
# Update-in-place files hold ONE entry per key: correct an entry by editing
# its row/block, never by appending a second one (its prior value is in git
# history). This is the opposite of the append-only logs. 'check' flags
# duplicate keys in system/ai-models.md (key = Agent, Model) and
# system/environments.md (key = the "Identify by:" line).

[CmdletBinding()]
param(
  [Parameter(Position = 0)] [string] $Command = '',
  [Parameter(ValueFromRemainingArguments = $true)] [string[]] $RestArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say { param([string]$Message) Write-Output $Message }
function ErrLine { param([string]$Message) [Console]::Error.WriteLine("context-mem: $Message") }
function Die { param([string]$Message) ErrLine $Message; exit 2 }

$scriptDir = $PSScriptRoot
$coreDir = (Resolve-Path (Join-Path $scriptDir '..')).Path
$contextDir = Split-Path -Parent $coreDir
$projectDir = Split-Path -Parent $contextDir
$memoryDir = Join-Path $contextDir 'memory'

function Usage {
  @(
    'context-mem - .context hygiene checks',
    '',
    '  check   duplicate keys in the update-in-place registries',
    '          (ai-models.md by Agent+Model, environments.md by Identify-by)',
    '  lint    .context vocabulary (ADR-N, bug IDs, .context/ paths) leaking',
    '          into the staged product diff',
    '  prune   advise archiving resolved/superseded entries out of the',
    '          append-only durable logs; --list names them. Reports only.',
    '',
    'Exit codes: check/lint 0 clean, 1 problem; prune always 0; 2 usage/error'
  ) | ForEach-Object { Say $_ }
  exit 2
}

function Check-AiModels {
  $f = Join-Path $memoryDir 'system/ai-models.md'
  if (-not (Test-Path -LiteralPath $f)) { return $true }
  $seen = @{}; $where = @{}; $ln = 0
  foreach ($raw in Get-Content -LiteralPath $f) {
    $ln++
    $line = $raw.TrimEnd("`r")
    if ($line -notmatch '^\s*\|') { continue }
    $cells = $line.Split('|')
    if ($cells.Count -lt 6) { continue }
    $a = $cells[1].Trim(); $m = $cells[2].Trim()
    $fs = $cells[3].Trim(); $ls = $cells[4].Trim(); $s = $cells[5].Trim()
    if ($fs -match '^\d{4}-\d{2}-\d{2}$' -and $ls -match '^\d{4}-\d{2}-\d{2}$' -and $s -match '^\d+$') {
      $key = "$a`t$m"
      if ($seen.ContainsKey($key)) { $seen[$key]++; $where[$key] += " $ln" }
      else { $seen[$key] = 1; $where[$key] = "$ln" }
    }
  }
  $dup = $false
  foreach ($k in $seen.Keys) {
    if ($seen[$k] -gt 1) {
      $parts = $k.Split("`t")
      ErrLine ('DUP ai-models.md: {0} rows for agent="{1}" model="{2}" (lines {3}) - merge into one row; sessions accumulate, old values are in git history' -f $seen[$k], $parts[0], $parts[1], $where[$k].Trim())
      $dup = $true
    }
  }
  return (-not $dup)
}

function Check-Environments {
  $f = Join-Path $memoryDir 'system/environments.md'
  if (-not (Test-Path -LiteralPath $f)) { return $true }
  $seen = @{}; $where = @{}; $ln = 0
  foreach ($raw in Get-Content -LiteralPath $f) {
    $ln++
    $line = $raw.TrimEnd("`r")
    if ($line -notmatch '^\s*-\s*\*\*Identify by:\*\*') { continue }
    $v = ($line -replace '^\s*-\s*\*\*Identify by:\*\*\s*', '').Trim()
    if ($v -eq '' -or $v -match '^<') { continue }
    if ($seen.ContainsKey($v)) { $seen[$v]++; $where[$v] += " $ln" }
    else { $seen[$v] = 1; $where[$v] = "$ln" }
  }
  $dup = $false
  foreach ($k in $seen.Keys) {
    if ($seen[$k] -gt 1) {
      ErrLine ('DUP environments.md: {0} blocks with Identify by="{1}" (lines {2}) - merge into one block; keep the latest facts, old ones are in git history' -f $seen[$k], $k, $where[$k].Trim())
      $dup = $true
    }
  }
  return (-not $dup)
}

function Invoke-Lint {
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die 'lint needs git on PATH' }
  $root = (& git -C $projectDir rev-parse --show-toplevel 2>$null)
  if (-not $root) { Die 'lint must run inside the project git repo' }
  $diff = (& git -C $root diff --cached -U0 --no-color 2>$null)
  $file = ''; $n = 0
  foreach ($line in $diff) {
    if ($line -match '^\+\+\+ ') { $file = $line -replace '^\+\+\+ b/', '' -replace '^\+\+\+ ', ''; continue }
    if ($line -match '^\+' -and $line -notmatch '^\+\+\+') {
      if ($file -match '^\.context/' -or $file -eq '/dev/null') { continue }
      $s = $line.Substring(1)
      $pat = ''
      if ($s -match 'ADR-[0-9]') { $pat = 'an ADR reference' }
      elseif ($s -match 'B-[0-9]{4}-[0-9]{2}-[0-9]') { $pat = 'a bug-ID reference' }
      elseif ($s -match '\.context/') { $pat = 'a .context/ path' }
      elseif ($s.ToLower() -match 'per adr') { $pat = '"per ADR"' }
      if ($pat -ne '') { ErrLine ('LEAK: {0} cites {1}: {2}' -f $file, $pat, $s); $n++ }
    }
  }
  if ($n -eq 0) { Say 'lint passed: no .context vocabulary (ADR-N, bug IDs, .context/ paths) in the staged product diff'; return $true }
  ErrLine 'lint failed: product code must stand on its own. State the reason in plain words; the ADR or bug-ID link belongs in .context/memory, not the source. Memory references code, never the reverse.'
  return $false
}

function Invoke-Prune {
  param([bool]$List)
  if (-not (Test-Path -LiteralPath $memoryDir)) { Say 'context-mem: no memory dir (nothing to prune)'; return }
  $eligible = $false
  foreach ($rel in @('flaws/log.md', 'inefficiencies/log.md')) {
    $f = Join-Path $memoryDir $rel
    if (-not (Test-Path -LiteralPath $f)) { continue }
    $total = 0; $lines = 0; $inseg = $false; $closed = $false; $heading = ''; $cand = @()
    foreach ($raw in Get-Content -LiteralPath $f) {
      $lines++
      $line = $raw.TrimEnd("`r")
      if ($line -match '^## ') {
        if ($inseg -and $closed) { $cand += $heading }
        $inseg = $true; $closed = $false; $heading = $line; $total++
        continue
      }
      if ($inseg -and ($line -match 'RESOLVED|[Ss]uperseded|[Ff]ixed in package|no longer (a )?(flaw|issue)')) { $closed = $true }
    }
    if ($inseg -and $closed) { $cand += $heading }
    $c = $cand.Count
    Say ('{0} - {1} entries ({2} lines); {3} marked resolved/superseded -> archive-eligible.' -f $rel, $total, $lines, $c)
    if ($c -gt 0) {
      $dir = $rel -replace '[^/]*$', ''
      Say ('  move the resolved entries to {0}archive.md; startup then reads only the active log.' -f $dir)
      if ($List) { foreach ($h in $cand) { Say ('    - {0}' -f $h) } }
      $eligible = $true
    }
  }
  if ($eligible) {
    Say ''
    Say 'memory prune: advisory only - nothing was moved. Archiving is a manual edit'
    Say '(cut the resolved entries into archive.md); they stay grep-able and out of the'
    Say 'startup read. Re-run with --list to see the eligible entries.'
  } else {
    Say 'memory prune: durable logs are lean - nothing archive-eligible.'
  }
}

switch ($Command) {
  'check' {
    if (-not (Test-Path -LiteralPath $memoryDir)) { Say 'context-mem: no memory dir (nothing to check)'; exit 0 }
    $ok1 = Check-AiModels
    $ok2 = Check-Environments
    if ($ok1 -and $ok2) { Say 'memory check passed: no duplicate keys in the update-in-place registries'; exit 0 }
    ErrLine 'memory check failed: a registry has more than one entry for a key - correct in place (edit the entry), do not append a duplicate'
    exit 1
  }
  'lint' {
    if (Invoke-Lint) { exit 0 } else { exit 1 }
  }
  'prune' {
    Invoke-Prune -List:($RestArgs -contains '--list')
    exit 0
  }
  { $_ -in @('', '-h', '--help', 'help') } { Usage }
  default { Die "unknown command '$Command' (try: context-mem.ps1 help)" }
}
