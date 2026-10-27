#!/usr/bin/env pwsh
# ledger-guard.ps1 -- Windows port of ledger-guard (see the sh edition for the
# full description). SOURCE ENCODING - pure ASCII, same rule as ledger-gates.ps1.
#
# Commands:
#   install [--force]   install the git pre-commit hook and the Claude Code hooks
#   status              show what is installed and the gate-pass state of the index
#   remind              print the protocol floor + live roster + current task
#   tool-check          PreToolUse hook: tool-call JSON on stdin; exit 2 blocks a
#                       masked gate verdict and --no-verify
#   git-pre-commit      the git hook check (git itself runs the sh edition)

[CmdletBinding()]
param(
  [Parameter(Position = 0)] [string] $Command = '',
  [Parameter(Position = 1, ValueFromRemainingArguments = $true)] [string[]] $Rest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say { param([string]$Message) Write-Output $Message }
function Err { param([string]$Message) [Console]::Error.WriteLine("ledger-guard: $Message") }
function Die { param([string]$Message) Err $Message; exit 2 }
function Usage {
  @('Commands:', '  install [--force] [--ci]', '  status', '  remind', '  tool-check', '  git-pre-commit',
    '  sessions | heartbeat S<NNN> [Name] | release S<NNN> | push-check [range]   (run through the sh edition)') | ForEach-Object { Say $_ }
  exit 2
}

$coreDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ledgerDir = Split-Path -Parent $coreDir
$leaf = Split-Path -Leaf $ledgerDir
if ($leaf -eq '.context_ledger' -or $leaf -eq '.context') { $projectDir = Split-Path -Parent $ledgerDir; $ledgerName = $leaf } else { $projectDir = $ledgerDir; $ledgerName = '' }
$memoryDir = Join-Path $ledgerDir 'memory'
if ($ledgerName) { $rel = "$ledgerName/core/bin" } else { $rel = 'core/bin' }

function Git-Out { param([string[]]$GitArgs)
  $o = & git -C $projectDir @GitArgs 2>$null
  if ($LASTEXITCODE -ne 0) { return '' }
  return (@($o) -join "`n").Trim()
}
function Git-Dir { return (Git-Out @('rev-parse', '--absolute-git-dir')) }
function Marker-State {
  $gd = Git-Dir
  if (-not $gd) { return 'none' }
  $mf = Join-Path $gd 'ledger-gate-pass'
  if (-not (Test-Path -LiteralPath $mf -PathType Leaf)) { return 'none' }
  $mt = ''
  foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $mf) { if ($line -match '^tree=(.+)$') { $mt = $matches[1].Trim(); break } }
  $it = Git-Out @('write-tree')
  if ($it -and $mt -eq $it) { return 'fresh' } else { return 'stale' }
}
function Hooks-Dir {
  $h = Git-Out @('rev-parse', '--git-path', 'hooks')
  if (-not $h) { return '' }
  if (-not [System.IO.Path]::IsPathRooted($h)) { $h = Join-Path $projectDir $h }
  return $h
}

function Cmd-ToolCheck {
  $in = [Console]::In.ReadToEnd()
  if ($in -notmatch 'ledger-gates' -and $in -notmatch '--no-verify') { return 0 }
  if ($in -match 'git\s[^|;&"]*(commit|push)[^|;&"]*--no-verify') {
    Err 'BLOCKED -- --no-verify skips the pre-commit gate hook. Run the gate and commit normally.'
    return 2
  }
  # a backslash, backtick or ')' ends the match: in the tool-call JSON a newline is \n,
  # so prose that merely names the tool cannot reach a pipe on a later line
  if ($in -match 'ledger-gates(\.ps1|\.cmd)?\s+(run|checkpoint)([^|;&\\`)]|>&[0-9])*\|([^|]|$)') {
    Err 'BLOCKED -- a ledger-gates verdict is being piped (tail/head/grep...). The consumer can mask a red gate and cut the output you need. Run the gate bare, or redirect to a file and read the verdict line.'
    return 2
  }
  return 0
}

function Cmd-Remind {
  Say '[ledger-guard] protocol reminder'
  $f = Join-Path $coreDir 'templates/guard-reminder.md'
  if (Test-Path -LiteralPath $f -PathType Leaf) { foreach ($l in Get-Content -Encoding UTF8 -LiteralPath $f) { Say $l } }
  $r = Join-Path $memoryDir 'office/agents/roster.md'
  if (Test-Path -LiteralPath $r -PathType Leaf) {
    Say 'Board (rows not Done):'
    foreach ($l in Get-Content -Encoding UTF8 -LiteralPath $r) {
      if ($l -match '^\|') {
        $c = @($l.Split('|') | ForEach-Object { $_.Trim() })
        if ($c.Count -ge 7 -and $c[2] -match '^S\d+$' -and $c[5] -ne 'Done') {
          $d = $c[6]; if ($d.Length -gt 100) { $d = $d.Substring(0, 100) }
          Say ("  - " + $c[1] + ' (' + $c[2] + ') ' + $c[5] + ': ' + $d)
        }
      }
    }
  }
  $cur = Join-Path $memoryDir 'office/tasks/current.md'
  if (Test-Path -LiteralPath $cur -PathType Leaf) {
    $t = '?'; $s = '?'
    foreach ($l in Get-Content -Encoding UTF8 -LiteralPath $cur) {
      if ($l -match '^- \*\*Task:\*\*\s*(.*)$') { $t = $matches[1] }
      elseif ($l -match '^- \*\*Status:\*\*\s*(.*)$') { $s = $matches[1] }
    }
    Say "Current task: $t [$s]"
  }
  Say "Pre-commit gate vs. staged tree: $(Marker-State)"
  return 0
}

function Hook-Snippet {
  # the command string sits inside JSON, so its own quotes are backslash-escaped
  $p = '\"$CLAUDE_PROJECT_DIR/' + $rel + '/ledger-guard.cmd\"'
  @(
    '{',
    '  "hooks": {',
    ('    "SessionStart": [{ "hooks": [{ "type": "command", "command": "' + $p + ' remind" }] }],'),
    ('    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "' + $p + ' remind" }] }],'),
    ('    "PreToolUse": [{ "matcher": "Bash", "hooks": [{ "type": "command", "command": "' + $p + ' tool-check" }] }]'),
    '  }',
    '}'
  )
}

function Cmd-Install { param([string[]]$InstallArgs)
  $force = ($null -ne $InstallArgs -and $InstallArgs -contains '--force')
  $ci = ($null -ne $InstallArgs -and $InstallArgs -contains '--ci')
  if (-not (Git-Dir)) { Die "not a git repository: $projectDir" }
  $hd = Hooks-Dir
  New-Item -ItemType Directory -Path $hd -Force | Out-Null
  foreach ($h in @('pre-commit', 'prepare-commit-msg', 'pre-push')) {
    $hk = Join-Path $hd $h
    $existing = ''
    if (Test-Path -LiteralPath $hk -PathType Leaf) { $existing = [System.IO.File]::ReadAllText($hk) }
    if ($existing -and $existing -notmatch 'ledger-guard' -and -not $force) {
      Err "a $h hook already exists and is not ledger-guard's: $hk"
      Err "  re-run with --force to replace it, or add a call to ledger-guard git-$h yourself."
    } else {
      # git runs hooks with its own sh, so the hook body is the POSIX script; LF endings, no BOM.
      $body = "#!/bin/sh`n# installed by ledger-guard ($h) -- see core/CHANGELOG.md`nexec sh `"`$(git rev-parse --show-toplevel)/$rel/ledger-guard`" git-$h `"`$@`"`n"
      [System.IO.File]::WriteAllText($hk, $body, (New-Object System.Text.UTF8Encoding($false)))
      Say "installed git $h hook: $hk"
    }
  }
  if ($ci) {
    $tpl = Join-Path $coreDir 'templates/ci/ledger-guard.yml'
    $out = Join-Path $projectDir '.github/workflows/ledger-guard.yml'
    if (-not (Test-Path -LiteralPath $tpl -PathType Leaf)) { Die "CI template missing: $tpl" }
    if (Test-Path -LiteralPath $out -PathType Leaf) { Say '.github/workflows/ledger-guard.yml already exists -- left alone' }
    else {
      New-Item -ItemType Directory -Path (Split-Path -Parent $out) -Force | Out-Null
      $dirName = $ledgerName; if (-not $dirName) { $dirName = '.context_ledger' }
      $text = ([System.IO.File]::ReadAllText($tpl)).Replace('__LEDGER__', $dirName)
      [System.IO.File]::WriteAllText($out, $text, (New-Object System.Text.UTF8Encoding($false)))
      Say 'wrote .github/workflows/ledger-guard.yml (core integrity + push-check on every push and PR)'
      Say 'NOTE: commit it on its own -- it is project tooling, not ledger memory'
    }
  }
  $cs = Join-Path $projectDir '.claude/settings.json'
  if ((Test-Path -LiteralPath $cs -PathType Leaf) -and ([System.IO.File]::ReadAllText($cs) -match 'ledger-guard')) {
    Say 'Claude Code hooks already present in .claude/settings.json'
  } elseif (Test-Path -LiteralPath $cs -PathType Leaf) {
    Say 'NOTICE: .claude/settings.json exists -- merge this "hooks" block into it yourself:'
    Hook-Snippet | ForEach-Object { Say $_ }
  } else {
    New-Item -ItemType Directory -Path (Join-Path $projectDir '.claude') -Force | Out-Null
    [System.IO.File]::WriteAllText($cs, ((Hook-Snippet) -join "`n") + "`n", (New-Object System.Text.UTF8Encoding($false)))
    Say 'wrote .claude/settings.json (Claude Code hooks: SessionStart + UserPromptSubmit remind, PreToolUse tool-check)'
    Say 'NOTE: commit it on its own -- it is project tooling, not ledger memory'
  }
}

function Cmd-Status {
  $hk = Join-Path (Hooks-Dir) 'pre-commit'
  if ((Test-Path -LiteralPath $hk -PathType Leaf) -and ([System.IO.File]::ReadAllText($hk) -match 'ledger-guard')) { Say 'git pre-commit hook: installed' } else { Say 'git pre-commit hook: MISSING (run: ledger-guard install)' }
  $cs = Join-Path $projectDir '.claude/settings.json'
  if ((Test-Path -LiteralPath $cs -PathType Leaf) -and ([System.IO.File]::ReadAllText($cs) -match 'ledger-guard')) { Say 'Claude Code hooks: installed' } else { Say 'Claude Code hooks: not installed (run: ledger-guard install)' }
  Say "pre-commit gate vs. staged tree: $(Marker-State)"
}

function Cmd-GitPreCommit {
  if ($env:LEDGER_GUARD_SKIP -eq '1') { Err 'WARNING: LEDGER_GUARD_SKIP=1 -- committing WITHOUT a fresh pre-commit gate pass'; return 0 }
  $gd = Git-Dir
  if ($gd -and ((Test-Path (Join-Path $gd 'rebase-merge')) -or (Test-Path (Join-Path $gd 'rebase-apply')) -or (Test-Path (Join-Path $gd 'MERGE_HEAD')) -or (Test-Path (Join-Path $gd 'CHERRY_PICK_HEAD')) -or (Test-Path (Join-Path $gd 'REVERT_HEAD')))) {
    Err 'notice: merge/rebase/cherry-pick in progress -- gate-pass check skipped'; return 0
  }
  if ((Marker-State) -eq 'fresh') { return 0 }
  Err 'BLOCKED: no fresh pre-commit gate pass for the staged tree.'
  Err "  Stage exactly what you will commit, then run: $rel/ledger-gates run pre-commit"
  return 1
}

if ($Command -in @('', '-h', '--help', 'help')) { Usage }
$restArgs = @(); if ($null -ne $Rest) { $restArgs += $Rest }
switch ($Command) {
  'install' { Cmd-Install $restArgs }
  'status' { Cmd-Status }
  # remind prefers the sh edition when one is on PATH (Git for Windows ships it): the
  # session-identity and stale-row lines live there only. Without sh, the plain reminder runs.
  'remind' { if (Get-Command sh -ErrorAction SilentlyContinue) { & sh (Join-Path $PSScriptRoot 'ledger-guard') remind; exit $LASTEXITCODE } else { [void](Cmd-Remind) } }
  'tool-check' { exit (Cmd-ToolCheck) }
  'git-pre-commit' { exit (Cmd-GitPreCommit) }
  # Session identity and push-time checks are implemented once, in the sh edition: git runs
  # its hooks with its own sh, so the sh edition must exist and work on every machine anyway.
  { $_ -in @('sessions', 'heartbeat', 'release', 'push-check', 'git-prepare-commit-msg', 'git-pre-push') } {
    if (-not (Get-Command sh -ErrorAction SilentlyContinue)) { Die "'$Command' needs sh on PATH (Git for Windows provides it)" }
    & sh (Join-Path $PSScriptRoot 'ledger-guard') $Command @restArgs
    exit $LASTEXITCODE
  }
  default { Die "unknown command '$Command' (try: ledger-guard.ps1 help)" }
}
