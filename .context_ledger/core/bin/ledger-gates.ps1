#!/usr/bin/env pwsh
# ledger-gates.ps1 -- Windows lifecycle gates for project agents.
#
# Commands:
#   init
#   checkpoint [--session ID --issue ID]
#   run pre-commit
#   run integration --session ID --issue ID
#   run exit

[CmdletBinding()]
param(
  [Parameter(Position = 0)] [string] $Command = '',
  [Parameter(Position = 1)] [string] $Gate = '',
  [Parameter(Position = 2, ValueFromRemainingArguments = $true)] [string[]] $Rest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say { param([string]$Message) Write-Output $Message }
# Gate logs use the host stream on purpose: if they flowed through the
# return pipeline, a caller's `if (-not (Run-One ...))` would compare an
# ARRAY (Say lines + the bool) and -not on a non-empty array is always
# $false -- every gate failure would read as a pass.
function Log { param([string]$Message) Write-Host $Message }
function Die { param([string]$Message) [Console]::Error.WriteLine("ledger-gates: $Message"); exit 2 }
function Usage {
  @(
    'Commands:',
    '  init',
    '  checkpoint [--session ID --issue ID]',
    '  run pre-commit',
    '  run integration --session ID --issue ID',
    '  run exit',
    '',
    'Explicit commands live in .context_ledger/memory/workflows/gates.conf.'
  ) | ForEach-Object { Say $_ }
  exit 2
}

$scriptDir = $PSScriptRoot
$coreDir = (Resolve-Path (Join-Path $scriptDir '..')).Path
$ledgerDir = Split-Path -Parent $coreDir
$leaf = Split-Path -Leaf $ledgerDir
if ($leaf -eq '.context_ledger' -or $leaf -eq '.context') { $projectDir = Split-Path -Parent $ledgerDir } else { $projectDir = $ledgerDir }
$memoryDir = Join-Path $ledgerDir 'memory'
$config = Join-Path $memoryDir 'workflows/gates.conf'

function Valid-Id { param([string]$Value) return ($Value -match '^[A-Za-z0-9._:-]+$') }
# Invoke a sibling .ps1. A child .ps1's `exit N` does not reliably set
# $LASTEXITCODE on every host (and reading it unset trips StrictMode), so
# pre-seed it and fall back to the child's success status. Child stdout is
# re-emitted on the host stream: if it flowed through the return pipeline,
# a caller's `$code -ne 0` comparison would filter the output array instead
# of comparing the exit code.
function Invoke-ChildScript { param([string]$Path, [string[]]$ScriptArgs = @())
  $global:LASTEXITCODE = $null
  $out = & $Path @ScriptArgs
  foreach ($line in @($out)) { if ($null -ne $line) { Write-Host $line } }
  if ($null -ne $LASTEXITCODE) { $script:ChildExit = $LASTEXITCODE }
  elseif ($?) { $script:ChildExit = 0 }
  else { $script:ChildExit = 1 }
}
function Run-One { param([string]$Label, [string]$Text)
  Log "GATE command: $Label -> $Text"
  $status = 0
  Push-Location $projectDir
  try {
    # $LASTEXITCODE is only written by native executables; resetting it first
    # keeps a cmdlet-only command from inheriting a stale previous exit code.
    $global:LASTEXITCODE = $null
    & ([scriptblock]::Create($Text))
    if ($null -ne $LASTEXITCODE) { $status = $LASTEXITCODE }
    elseif (-not $?) { $status = 1 }
  } catch {
    $status = 1
    [Console]::Error.WriteLine("ledger-gates: ERROR: $($_.Exception.Message)")
  } finally { Pop-Location }
  if ($status -ne 0) { [Console]::Error.WriteLine("ledger-gates: FAILED ($status): $Text"); return $false }
  Log "PASSED: $Text"; return $true
}
function Config-Mode {
  if (-not (Test-Path -LiteralPath $config -PathType Leaf)) { return 'hybrid' }
  $line = Get-Content -LiteralPath $config | Where-Object { $_ -match '^mode=' } | Select-Object -First 1
  if ($null -eq $line) { return 'hybrid' } else { return ($line -replace '^mode=', '') }
}
function Explicit-Commands { param([string]$RequestedGate)
  $commands = @()
  if (Test-Path -LiteralPath $config -PathType Leaf) {
    foreach ($line in Get-Content -LiteralPath $config) {
      if ($line -match "^$RequestedGate\|(.+)$") { $commands += $matches[1] }
    }
  }
  return $commands
}
function Package-Manager {
  if ((Test-Path (Join-Path $projectDir 'bun.lock') -PathType Leaf) -or (Test-Path (Join-Path $projectDir 'bun.lockb') -PathType Leaf)) { return 'bun' }
  if (Test-Path (Join-Path $projectDir 'pnpm-lock.yaml') -PathType Leaf) { return 'pnpm' }
  if (Test-Path (Join-Path $projectDir 'yarn.lock') -PathType Leaf) { return 'yarn' }
  if (Test-Path (Join-Path $projectDir 'package-lock.json') -PathType Leaf) { return 'npm' }
  return ''
}
function Package-Scripts {
  $package = Join-Path $projectDir 'package.json'
  if (-not (Test-Path -LiteralPath $package -PathType Leaf)) { return @() }
  try { return @((Get-Content -LiteralPath $package -Raw | ConvertFrom-Json).scripts.PSObject.Properties.Name) }
  catch { return @() }
}
function Discovered-Commands { param([string]$RequestedGate)
  $commands = @(); $pm = Package-Manager; $scripts = Package-Scripts
  if ($pm -and $scripts.Count -gt 0) {
    foreach ($script in @('typecheck','lint','test','build')) {
      $include = (($RequestedGate -eq 'pre-commit' -and $script -in @('typecheck','lint','test')) -or
                  ($RequestedGate -eq 'integration' -and $script -eq 'build') -or
                  ($RequestedGate -eq 'exit' -and $script -eq 'test'))
      if ($include -and $scripts -contains $script) { $commands += "$pm run $script" }
    }
  } elseif ((Test-Path (Join-Path $projectDir 'pyproject.toml') -PathType Leaf) -or (Test-Path (Join-Path $projectDir 'pytest.ini') -PathType Leaf)) {
    if ($RequestedGate -in @('pre-commit','integration','exit') -and ((Test-Path (Join-Path $projectDir 'pytest.ini') -PathType Leaf) -or (Select-String -Path (Join-Path $projectDir 'pyproject.toml') -Pattern 'pytest' -Quiet))) { $commands += 'python -m pytest' }
    if ($RequestedGate -eq 'pre-commit' -and (Select-String -Path (Join-Path $projectDir 'pyproject.toml') -Pattern 'ruff' -Quiet)) { $commands += 'ruff check .' }
  }
  return $commands
}
# NOTE: never name a PowerShell parameter $Args - it collides with the
# automatic variable of the same name, and flag tokens (--session ...)
# are silently lost before the loop ever sees them.
function Parse-Scope { param([string[]]$ScopeArgs)
  $scope = @{ Session = ''; Issue = '' }
  for ($i = 0; $i -lt $ScopeArgs.Count; $i++) {
    switch ($ScopeArgs[$i]) {
      '--session' { if ($i + 1 -ge $ScopeArgs.Count) { Die '--session needs a value' }; $scope.Session = $ScopeArgs[++$i] }
      '--issue' { if ($i + 1 -ge $ScopeArgs.Count) { Die '--issue needs a value' }; $scope.Issue = $ScopeArgs[++$i] }
      default { Die "unknown argument '$($ScopeArgs[$i])'" }
    }
  }
  if ($scope.Session -and -not (Valid-Id $scope.Session)) { Die "invalid session id: $($scope.Session)" }
  if ($scope.Issue -and -not (Valid-Id $scope.Issue)) { Die "invalid issue id: $($scope.Issue)" }
  return $scope
}
function Run-ProjectCommands { param([string]$RequestedGate)
  $explicit = @(Explicit-Commands $RequestedGate)
  # @() wraps the whole if-statement: a branch's @() alone does not survive
  # the pipeline unroll, and zero commands would leave $commands = $null.
  $commands = @(if ($explicit.Count -gt 0) { $explicit } elseif ((Config-Mode) -eq 'hybrid') { Discovered-Commands $RequestedGate })
  if ($explicit.Count -eq 0 -and (Config-Mode) -eq 'explicit' -and $commands.Count -eq 0) { [Console]::Error.WriteLine("ledger-gates: $RequestedGate has no explicit commands in $config"); return $false }
  $failed = $false
  foreach ($text in $commands) { if (-not (Run-One "$RequestedGate (configured/discovered)" $text)) { $failed = $true } }
  if ($commands.Count -eq 0) { Log "NOTICE: no project commands discovered for $RequestedGate; configure $config for a mandatory project check" }
  return (-not $failed)
}
function Checkpoint { param([string[]]$CheckpointArgs)
  $scope = Parse-Scope $CheckpointArgs
  Say "GATE checkpoint: $([DateTime]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"))"
  Say 'Working tree:'; & git -C $projectDir status --short
  # advisory nudge (never blocks): an office at capacity should close before
  # more sessions log into it
  $sm = Join-Path $memoryDir 'office/agents/sessions.md'
  if (Test-Path -LiteralPath $sm) {
    $sc = 0
    foreach ($raw in Get-Content -LiteralPath $sm) { if ($raw -match '^## \d{4}-\d{2}-\d{2}.*Session ') { $sc++ } }
    $os = 0; $gsz = 0
    $hc = Join-Path $memoryDir 'workflows/history.conf'
    if (Test-Path -LiteralPath $hc) {
      foreach ($raw in Get-Content -LiteralPath $hc) {
        $line = $raw.TrimEnd("`r")
        if ($line -match '^office_size=(\d+)') { $os = [int]$matches[1] }
        elseif ($line -match '^group_size=(\d+)') { $gsz = [int]$matches[1] }
      }
    }
    $gs = $os; if ($gs -le 0) { $gs = $gsz }; if ($gs -le 0) { $gs = 20 }
    if ($sc -ge $gs) { Say "NOTICE: the office is full ($sc / $gs sessions) - run: ledger-history close" }
  }
  if ($scope.Session -and $scope.Issue) { & (Join-Path $coreDir 'bin/ledger-collab.ps1') status --session $scope.Session --issue $scope.Issue }
  Say 'CHECKPOINT PASSED: re-read the latest state before the next action'
}
function Run-Gate { param([string]$RequestedGate, [string[]]$GateArgs)
  if ($RequestedGate -notin @('pre-commit','integration','exit')) { Die "unknown gate: $RequestedGate" }
  $scope = Parse-Scope $GateArgs; $failed = $false
  if ($RequestedGate -eq 'pre-commit') {
    if (-not (Run-One 'pre-commit (universal)' 'git diff --cached --check')) { $failed = $true }
    if (-not (Run-ProjectCommands 'pre-commit')) { $failed = $true }
  } elseif ($RequestedGate -eq 'integration') {
    if (-not (Run-One 'integration (universal)' 'git diff --check')) { $failed = $true }
    if ($scope.Session -and $scope.Issue) {
      Invoke-ChildScript (Join-Path $coreDir 'bin/ledger-collab.ps1') @('check','--session',$scope.Session,'--issue',$scope.Issue)
      if ($script:ChildExit -ne 0) { $failed = $true }
    }
    else { Say 'NOTICE: no collaboration scope supplied; skipping ledger-collab check' }
    if (-not (Run-ProjectCommands 'integration')) { $failed = $true }
  } else {
    Invoke-ChildScript (Join-Path $coreDir 'bin/ledger-sync.ps1') @('verify')
    if ($script:ChildExit -ne 0) { $failed = $true }
    if (-not (Run-One 'exit (universal)' 'git diff --check')) { $failed = $true }
    if (-not (Run-ProjectCommands 'exit')) { $failed = $true }
  }
  if ($failed) { Die "$RequestedGate gate failed" }
  Say "GATE PASSED: $RequestedGate"
}
function Init-Config {
  if (Test-Path -LiteralPath $config) { Die "gate config already exists: $config" }
  New-Item -ItemType Directory -Path (Split-Path -Parent $config) -Force | Out-Null
  Copy-Item -LiteralPath (Join-Path $coreDir 'templates/memory/workflows/gates.conf') -Destination $config
  Say 'created .context_ledger/memory/workflows/gates.conf'; Say 'fill explicit project commands, then run ledger-gates checkpoint'
}

if ($Command -in @('', '-h', '--help', 'help')) { Usage }
switch ($Command) {
  'init' { Init-Config }
  'checkpoint' { $cmdArgs = @(); if ($Gate) { $cmdArgs += $Gate }; if ($null -ne $Rest) { $cmdArgs += $Rest }; Checkpoint $cmdArgs }
  'run' { $cmdArgs = @(); if ($null -ne $Rest) { $cmdArgs += $Rest }; Run-Gate $Gate $cmdArgs }
  default { Die "unknown command '$Command' (try: ledger-gates.ps1 help)" }
}
