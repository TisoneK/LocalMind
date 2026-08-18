#!/usr/bin/env pwsh
# context-gates.ps1 — Windows lifecycle gates for project agents.
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
function Die { param([string]$Message) [Console]::Error.WriteLine("context-gates: $Message"); exit 2 }
function Usage {
  @(
    'Commands:',
    '  init',
    '  checkpoint [--session ID --issue ID]',
    '  run pre-commit',
    '  run integration --session ID --issue ID',
    '  run exit',
    '',
    'Explicit commands live in .context/memory/workflows/gates.conf.'
  ) | ForEach-Object { Say $_ }
  exit 2
}

$scriptDir = $PSScriptRoot
$coreDir = (Resolve-Path (Join-Path $scriptDir '..')).Path
$contextDir = Split-Path -Parent $coreDir
if ((Split-Path -Leaf $contextDir) -eq '.context') { $projectDir = Split-Path -Parent $contextDir } else { $projectDir = $contextDir }
$memoryDir = Join-Path $contextDir 'memory'
$config = Join-Path $memoryDir 'workflows/gates.conf'

function Valid-Id { param([string]$Value) return ($Value -match '^[A-Za-z0-9._:-]+$') }
function Run-One { param([string]$Label, [string]$Text)
  Say "GATE command: $Label -> $Text"
  Push-Location $projectDir
  try { & ([scriptblock]::Create($Text)); $status = $LASTEXITCODE }
  finally { Pop-Location }
  if ($status -ne 0) { [Console]::Error.WriteLine("context-gates: FAILED ($status): $Text"); return $false }
  Say "PASSED: $Text"; return $true
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
  if (Test-Path (Join-Path $projectDir 'bun.lock') -PathType Leaf -or Test-Path (Join-Path $projectDir 'bun.lockb') -PathType Leaf) { return 'bun' }
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
  } elseif (Test-Path (Join-Path $projectDir 'pyproject.toml') -PathType Leaf -or Test-Path (Join-Path $projectDir 'pytest.ini') -PathType Leaf) {
    if ($RequestedGate -in @('pre-commit','integration','exit') -and (Test-Path (Join-Path $projectDir 'pytest.ini') -PathType Leaf -or (Select-String -Path (Join-Path $projectDir 'pyproject.toml') -Pattern 'pytest' -Quiet))) { $commands += 'python -m pytest' }
    if ($RequestedGate -eq 'pre-commit' -and (Select-String -Path (Join-Path $projectDir 'pyproject.toml') -Pattern 'ruff' -Quiet)) { $commands += 'ruff check .' }
  }
  return $commands
}
function Parse-Scope { param([string[]]$Args)
  $scope = @{ Session = ''; Issue = '' }
  for ($i = 0; $i -lt $Args.Count; $i++) {
    switch ($Args[$i]) {
      '--session' { if ($i + 1 -ge $Args.Count) { Die '--session needs a value' }; $scope.Session = $Args[++$i] }
      '--issue' { if ($i + 1 -ge $Args.Count) { Die '--issue needs a value' }; $scope.Issue = $Args[++$i] }
      default { Die "unknown argument '$($Args[$i])'" }
    }
  }
  if ($scope.Session -and -not (Valid-Id $scope.Session)) { Die "invalid session id: $($scope.Session)" }
  if ($scope.Issue -and -not (Valid-Id $scope.Issue)) { Die "invalid issue id: $($scope.Issue)" }
  return $scope
}
function Run-ProjectCommands { param([string]$RequestedGate)
  $explicit = @(Explicit-Commands $RequestedGate)
  $commands = if ($explicit.Count -gt 0) { $explicit } elseif ((Config-Mode) -eq 'hybrid') { @(Discovered-Commands $RequestedGate) } else { @() }
  if ($explicit.Count -eq 0 -and (Config-Mode) -eq 'explicit' -and $commands.Count -eq 0) { [Console]::Error.WriteLine("context-gates: $RequestedGate has no explicit commands in $config"); return $false }
  $failed = $false
  foreach ($text in $commands) { if (-not (Run-One "$RequestedGate (configured/discovered)" $text)) { $failed = $true } }
  if ($commands.Count -eq 0) { Say "NOTICE: no project commands discovered for $RequestedGate; configure $config for a mandatory project check" }
  return (-not $failed)
}
function Checkpoint { param([string[]]$Args)
  $scope = Parse-Scope $Args
  Say "GATE checkpoint: $([DateTime]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"))"
  Say 'Working tree:'; & git -C $projectDir status --short
  if ($scope.Session -and $scope.Issue) { & (Join-Path $coreDir 'bin/context-collab.ps1') status --session $scope.Session --issue $scope.Issue }
  Say 'CHECKPOINT PASSED: re-read the latest state before the next action'
}
function Run-Gate { param([string]$RequestedGate, [string[]]$Args)
  if ($RequestedGate -notin @('pre-commit','integration','exit')) { Die "unknown gate: $RequestedGate" }
  $scope = Parse-Scope $Args; $failed = $false
  if ($RequestedGate -eq 'pre-commit') {
    if (-not (Run-One 'pre-commit (universal)' 'git diff --cached --check')) { $failed = $true }
    if (-not (Run-ProjectCommands 'pre-commit')) { $failed = $true }
  } elseif ($RequestedGate -eq 'integration') {
    if (-not (Run-One 'integration (universal)' 'git diff --check')) { $failed = $true }
    if ($scope.Session -and $scope.Issue) { & (Join-Path $coreDir 'bin/context-collab.ps1') check --session $scope.Session --issue $scope.Issue; if ($LASTEXITCODE -ne 0) { $failed = $true } }
    else { Say 'NOTICE: no collaboration scope supplied; skipping context-collab check' }
    if (-not (Run-ProjectCommands 'integration')) { $failed = $true }
  } else {
    & (Join-Path $coreDir 'bin/context-sync.ps1') verify; if ($LASTEXITCODE -ne 0) { $failed = $true }
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
  Say 'created .context/memory/workflows/gates.conf'; Say 'fill explicit project commands, then run context-gates checkpoint'
}

if ($Command -in @('', '-h', '--help', 'help')) { Usage }
switch ($Command) {
  'init' { Init-Config }
  'checkpoint' { $args = @(); if ($Gate) { $args += $Gate }; if ($null -ne $Rest) { $args += $Rest }; Checkpoint $args }
  'run' { $args = @(); if ($null -ne $Rest) { $args += $Rest }; Run-Gate $Gate $args }
  default { Die "unknown command '$Command' (try: context-gates.ps1 help)" }
}
