#!/usr/bin/env pwsh
# context-sync.ps1 — Windows/PowerShell port of core/bin/context-sync.
#
# The POSIX sh script (core/bin/context-sync) is the reference implementation
# and runs on macOS/Linux. This port covers the commands a Windows agent hits
# inside a session; it is byte-compatible with the sh script's MANIFEST.sha256
# (same hashes, same forward-slash paths), so a core verified here verifies
# there and vice-versa. Never touches .context/memory/ except memory/core.lock.
#
# Requires PowerShell 5.1+ (Windows PowerShell or PowerShell 7 `pwsh`) and,
# for `rollback`, git on PATH.
#
# Commands (project mode — run as:
#     pwsh -File .context/core/bin/context-sync.ps1 <cmd>):
#   status               local core version + best reachable update source
#   verify               check every core file against core/MANIFEST.sha256
#   update [SOURCE]      replace core/ from SOURCE (package clone / unpacked
#                        archive). Same-MAJOR updates apply directly; a MAJOR
#                        bump needs -Major. Memory is never touched.
#   rollback [VERSION]   restore core/ from this project's git history
#                        (default VERSION: the one in memory/core.lock)
#   lock                 record the current verified core version in
#                        memory/core.lock (update/verify call this for you)
#
# Package-mode commands (manifest, bootstrap, harvest) are NOT ported —
# run them with the sh script on macOS/Linux.
#
# Exit codes: 0 ok · 1 failure · 2 usage · 3 verify mismatch

[CmdletBinding()]
param(
  [Parameter(Position = 0)]                     [string]   $Command = '',
  [Parameter(Position = 1, ValueFromRemainingArguments = $true)] [string[]] $Rest,
  [switch] $Major
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say  { param([string]$m) Write-Output $m }
function Err  { param([string]$m) [Console]::Error.WriteLine("context-sync: $m") }
function Die  { param([string]$m) Err $m; exit 1 }

# --- locate ourselves -------------------------------------------------------
$SCRIPT_DIR = $PSScriptRoot
$CORE_DIR   = (Resolve-Path (Join-Path $SCRIPT_DIR '..')).Path
$PARENT_DIR = Split-Path -Parent $CORE_DIR

if ((Split-Path -Leaf $PARENT_DIR) -eq '.context') {
  $script:MODE        = 'project'
  $script:CONTEXT_DIR = $PARENT_DIR
  $script:PROJECT_DIR = Split-Path -Parent $CONTEXT_DIR
  $script:MEMORY_DIR  = Join-Path $CONTEXT_DIR 'memory'
} else {
  $script:MODE        = 'package'   # running from a package clone
  $script:PACKAGE_DIR = $PARENT_DIR
}

# --- helpers ----------------------------------------------------------------
function Core-Version { # $dir -> version string
  param([string]$dir)
  $vf = Join-Path $dir 'VERSION'
  if (-not (Test-Path -LiteralPath $vf)) { return '0.0.0' }
  $line = (Get-Content -LiteralPath $vf -TotalCount 1)
  if ($null -eq $line) { return '0.0.0' }
  return ($line -replace '\s', '')
}

function Ver-Part { # $version $index(1..3) -> integer part
  param([string]$v, [int]$i)
  $parts = $v.Split('.')
  $p = if ($i -le $parts.Count) { $parts[$i - 1] } else { '' }
  $p = ($p -replace '[^0-9]', '')
  if ($p -eq '') { return 0 } else { return [int]$p }
}

function Ver-Cmp { # $a $b -> 'newer'|'same'|'older'  ($a relative to $b)
  param([string]$a, [string]$b)
  foreach ($i in 1, 2, 3) {
    $x = Ver-Part $a $i; $y = Ver-Part $b $i
    if ($x -gt $y) { return 'newer' }
    if ($x -lt $y) { return 'older' }
  }
  return 'same'
}

# a directory is a core source if it's a package clone (has core/) or an
# already-unpacked core (has VERSION + rules/). Returns the core dir, or $null.
function Source-Core-Dir {
  param([string]$path)
  if ((Test-Path -LiteralPath (Join-Path $path 'core/rules') -PathType Container) -and
      (Test-Path -LiteralPath (Join-Path $path 'core/VERSION') -PathType Leaf)) {
    return (Resolve-Path (Join-Path $path 'core')).Path
  }
  if ((Test-Path -LiteralPath (Join-Path $path 'rules') -PathType Container) -and
      (Test-Path -LiteralPath (Join-Path $path 'VERSION') -PathType Leaf)) {
    return (Resolve-Path $path).Path
  }
  return $null
}

function Find-Source { # $explicit -> core dir or $null
  param([string]$explicit)
  if ($explicit) {
    $d = Source-Core-Dir $explicit
    if (-not $d) { Die "not a package clone or core tree: $explicit" }
    return $d
  }
  if ($env:CONTEXT_PKG) {
    $d = Source-Core-Dir $env:CONTEXT_PKG
    if ($d) { return $d }
  }
  foreach ($rel in '../context', '../.context') {
    $cand = Join-Path $PROJECT_DIR $rel
    if (Test-Path -LiteralPath $cand) {
      $d = Source-Core-Dir $cand
      if ($d) { return $d }
    }
  }
  return $null
}

# Parse a MANIFEST.sha256 line into @{ Hash; Path } or $null.
# Format (sha256sum / shasum -a 256): "<64 hex>  <relpath>" — one separator
# space plus a mode char (space for text, '*' for binary).
function Parse-Manifest-Line {
  param([string]$line)
  if ($line -match '^([0-9a-fA-F]{64}) [ *](.+)$') {
    return @{ Hash = $matches[1].ToLower(); Path = $matches[2] }
  }
  return $null
}

# $dir -> $true clean, $false mismatch. Prints up to 20 problems to stderr.
function Verify-Tree {
  param([string]$dir)
  $manifest = Join-Path $dir 'MANIFEST.sha256'
  if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    Err "no MANIFEST.sha256 in $dir"; return $false
  }
  $problems = @()
  foreach ($line in Get-Content -LiteralPath $manifest) {
    if ($line.Trim() -eq '') { continue }
    $entry = Parse-Manifest-Line $line
    if (-not $entry) { continue }
    $file = Join-Path $dir ($entry.Path.Replace('/', [IO.Path]::DirectorySeparatorChar))
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
      $problems += "$($entry.Path): FAILED open or read"; continue
    }
    $got = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLower()
    if ($got -ne $entry.Hash) { $problems += "$($entry.Path): FAILED" }
  }
  if ($problems.Count -eq 0) { return $true }
  $problems | Select-Object -First 20 | ForEach-Object { [Console]::Error.WriteLine($_) }
  return $false
}

function Write-Lock { # $version
  param([string]$version)
  if ($MODE -ne 'project') { return }
  if (-not (Test-Path -LiteralPath $MEMORY_DIR)) {
    New-Item -ItemType Directory -Path $MEMORY_DIR -Force | Out-Null
  }
  $today = Get-Date -Format 'yyyy-MM-dd'
  $body = @(
    '# written by context-sync — the last-known-good core version.'
    '# Do not edit by hand. If core fails verify, `context-sync rollback`'
    '# restores the version recorded here from git history.'
    "version=$version"
    "verified=$today"
  ) -join "`n"
  Set-Content -LiteralPath (Join-Path $MEMORY_DIR 'core.lock') -Value ($body + "`n") -NoNewline
}

function Lock-Version {
  $lf = Join-Path $MEMORY_DIR 'core.lock'
  if (-not (Test-Path -LiteralPath $lf)) { return '' }
  foreach ($line in Get-Content -LiteralPath $lf) {
    if ($line -match '^version=(.*)$') { return $matches[1] }
  }
  return ''
}

function Need-Project {
  param([string]$name)
  if ($MODE -ne 'project') {
    Die "'$name' runs inside a project (.context/core/bin/context-sync.ps1), not the package clone"
  }
}

# --- commands ----------------------------------------------------------------
function Cmd-Status {
  param([string]$srcArg)
  Need-Project 'status'
  $localV = Core-Version $CORE_DIR
  Say "core:   $localV  (.context/core)"
  $locked = Lock-Version
  if ($locked -eq '') { $locked = '(no core.lock yet)' }
  Say "locked: $locked"
  $src = Find-Source $srcArg
  if ($src) {
    $srcV = Core-Version $src
    switch (Ver-Cmp $srcV $localV) {
      'newer' {
        if ((Ver-Part $srcV 1) -eq (Ver-Part $localV 1)) {
          Say "source: $srcV  ($src) — UPDATE AVAILABLE (same MAJOR: safe to 'update')"
        } else {
          Say "source: $srcV  ($src) — MAJOR update: read its CHANGELOG.md, then 'update -Major' with the user's go-ahead"
        }
      }
      'same'  { Say "source: $srcV  ($src) — up to date" }
      'older' { Say "source: $srcV  ($src) — source is OLDER than local; nothing to do" }
    }
  } else {
    Say "source: none reachable (no sibling package clone; set CONTEXT_PKG or pass a path) — skipping, this is fine"
  }
}

function Cmd-Verify {
  param([string]$target)
  if (-not $target) { $target = $CORE_DIR }
  if (Verify-Tree $target) {
    Say "core OK: every file matches MANIFEST.sha256 ($(Core-Version $target))"
    if ($target -eq $CORE_DIR) { Write-Lock (Core-Version $target) }
    exit 0
  }
  Err 'CORE INTEGRITY FAILURE — core/ does not match its manifest.'
  Err 'Do not ''fix'' core in place. Run: context-sync rollback'
  Err 'Then log the incident in memory/flaws/log.md and continue.'
  exit 3
}

function Cmd-Update {
  param([string[]]$uArgs)
  Need-Project 'update'
  $srcArg = ''
  foreach ($a in $uArgs) {
    if ($a -eq '--major') { $script:Major = $true } else { $srcArg = $a }
  }
  $src = Find-Source $srcArg
  if (-not $src) { Die 'no update source found (sibling clone, CONTEXT_PKG, or a path argument)' }
  $srcV = Core-Version $src; $localV = Core-Version $CORE_DIR
  switch (Ver-Cmp $srcV $localV) {
    'same'  { Say "already at $localV — nothing to do"; exit 0 }
    'older' { Say "source ($srcV) is older than local ($localV) — refusing to downgrade"; exit 0 }
  }
  if (((Ver-Part $srcV 1) -ne (Ver-Part $localV 1)) -and (-not $Major)) {
    Die "MAJOR version bump ($localV -> $srcV): read CHANGELOG.md migration notes, get the user's go-ahead, re-run with -Major"
  }
  if (-not (Verify-Tree $src)) { Die 'update source fails its own manifest — refusing to install a corrupt core' }

  $stage = Join-Path $CONTEXT_DIR 'core.new'
  if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
  Copy-Item -LiteralPath $src -Destination $stage -Recurse -Force
  if (-not (Verify-Tree $stage)) {
    Remove-Item -LiteralPath $stage -Recurse -Force
    Die 'staged copy fails verify — aborting, core untouched'
  }

  try {
    Remove-Item -LiteralPath $CORE_DIR -Recurse -Force
    Move-Item -LiteralPath $stage -Destination $CORE_DIR
  } catch {
    Die 'swap failed — restore .context/core from git (git checkout -- .context/core)'
  }
  Write-Lock $srcV
  # refresh the core-owned root file
  $readme = Join-Path $CORE_DIR 'templates/context-README.md'
  if (Test-Path -LiteralPath $readme) {
    Copy-Item -LiteralPath $readme -Destination (Join-Path $CONTEXT_DIR 'README.md') -Force -ErrorAction SilentlyContinue
  }
  Say "core updated: $localV -> $srcV"
  Say 'next: read the new entries in .context/core/CHANGELOG.md;'
  Say '      if templates/kickoff.md or templates/AGENTS.md changed materially,'
  Say '      regenerate .context/kickoff.md / AGENTS.md (facts from memory);'
  Say "      commit as: chore(context): update core to $srcV"
  exit 0
}

function Cmd-Rollback {
  param([string]$want)
  Need-Project 'rollback'
  if (-not $want) { $want = Lock-Version }
  if (-not $want) { Die 'no version given and no memory/core.lock — pass a version: context-sync rollback 0.2.0' }
  & git -C $PROJECT_DIR rev-parse --is-inside-work-tree *> $null
  if ($LASTEXITCODE -ne 0) { Die 'project is not a git repo — cannot roll back' }
  $found = ''
  $shas = & git -C $PROJECT_DIR log --format=%H -- .context/core/VERSION
  foreach ($sha in $shas) {
    $v = (& git -C $PROJECT_DIR show "${sha}:.context/core/VERSION" 2>$null | Select-Object -First 1)
    if ($null -ne $v) { $v = ($v -replace '\s', '') }
    if ($v -eq $want) { $found = $sha; break }
  }
  if (-not $found) { Die "no commit in history has core VERSION $want" }
  Remove-Item -LiteralPath (Join-Path $PROJECT_DIR '.context/core') -Recurse -Force
  & git -C $PROJECT_DIR checkout $found -- .context/core
  if ($LASTEXITCODE -ne 0) { Die 'git checkout failed — run: git checkout HEAD -- .context/core' }
  Write-Lock $want
  Say "core rolled back to $want (from commit $($found.Substring(0, [Math]::Min(8, $found.Length))))"
  Say 'log the incident in memory/flaws/log.md, then commit as:'
  Say "  chore(context): roll back core to $want"
  exit 0
}

# --- dispatch ----------------------------------------------------------------
$argsRest = if ($null -eq $Rest) { @() } else { $Rest }

switch ($Command) {
  'status'   { Cmd-Status ($argsRest | Select-Object -First 1); exit 0 }
  'verify'   { Cmd-Verify ($argsRest | Select-Object -First 1) }
  'update'   { Cmd-Update $argsRest }
  'rollback' { Cmd-Rollback ($argsRest | Select-Object -First 1) }
  'lock' {
    Need-Project 'lock'
    Write-Lock (Core-Version $CORE_DIR)
    Say "locked $(Core-Version $CORE_DIR)"
    exit 0
  }
  { $_ -in 'manifest', 'bootstrap', 'harvest' } {
    Die "'$Command' is not ported to PowerShell — run the sh script on macOS/Linux: sh core/bin/context-sync $Command"
  }
  { $_ -in '', $null, '-h', '--help', 'help' } {
    # print the command-doc comment (lines 13..28) as help, stripping '# '
    $self = Get-Content -LiteralPath $PSCommandPath
    $self[12..27] | ForEach-Object { Say ($_ -replace '^# ?', '') }
    exit 2
  }
  default { Die "unknown command: $Command (try: context-sync.ps1 help)" }
}
