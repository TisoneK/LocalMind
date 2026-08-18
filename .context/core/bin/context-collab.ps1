#!/usr/bin/env pwsh
# context-collab.ps1 — PowerShell peer coordination helper.
#
# Coordination state is immutable, one-file-per-event under
# .context/memory/collaboration/events/. Product changes still belong on an
# isolated branch/worktree and are never merged by this helper.
#
# Usage:
#   pwsh -File .context/core/bin/context-collab.ps1 emit claim `
#     --session ID --agent ID --issue ID --paths src/a.py `
#     --body-file C:\path\claim.md
#   pwsh -File .context/core/bin/context-collab.ps1 status --session ID --issue ID
#   pwsh -File .context/core/bin/context-collab.ps1 check --session ID --issue ID

[CmdletBinding()]
param(
  [Parameter(Position = 0)] [string] $Command = '',
  [Parameter(Position = 1)] [string] $Type = '',
  [Parameter(Position = 2, ValueFromRemainingArguments = $true)] [string[]] $Rest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say { param([string]$Message) Write-Output $Message }
function Die { param([string]$Message) [Console]::Error.WriteLine("context-collab: $Message"); exit 1 }
function Usage {
  @(
    'Commands:',
    '  emit TYPE --session ID --agent ID --issue ID [metadata] [--body-file FILE]',
    '  status [--session ID] [--issue ID]',
    '  check  [--session ID] [--issue ID]   integration-readiness gate',
    '',
    'Metadata: --paths CSV --refs CSV --option ID --selected ID --owner ID',
    '          --participants CSV --body TEXT --body-file FILE',
    '',
    'Event types: claim proposal assessment agreement correction handoff release'
  ) | ForEach-Object { Say $_ }
  exit 2
}

$scriptDir = $PSScriptRoot
$coreDir = (Resolve-Path (Join-Path $scriptDir '..')).Path
$contextDir = Split-Path -Parent $coreDir
$eventDir = Join-Path $contextDir 'memory/collaboration/events'

function Validate-Value { param([string]$Name, [string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value) -or $Value.Contains("`n") -or $Value.Contains("`r")) {
    Die "$Name cannot be empty or contain a newline"
  }
}
function Validate-Id { param([string]$Name, [string]$Value)
  Validate-Value $Name $Value
  if ($Value -notmatch '^[A-Za-z0-9._:-]+$') { Die "$Name may contain only letters, numbers, '.', '_', ':' or '-'" }
}
function Metadata { param([string]$Name, [string]$Value)
  if ($Value -eq '') { return 'none' } else { return $Value }
}
function Parse-Options { param([string[]]$Args)
  $result = @{
    session = ''; agent = ''; issue = ''; paths = 'none'; refs = 'none'; option = 'none'
    selected = 'none'; owner = 'none'; participants = 'none'; body = ''; bodyFile = ''
  }
  for ($i = 0; $i -lt $Args.Count; $i++) {
    $key = $Args[$i]
    if ($key -in @('--session','--agent','--issue','--paths','--refs','--option','--selected','--owner','--participants','--body','--body-file')) {
      if ($i + 1 -ge $Args.Count) { Die "$key needs a value" }
      $name = switch ($key) {
        '--body-file' { 'bodyFile' }
        default { $key.Substring(2) }
      }
      $result[$name] = $Args[$i + 1]; $i++
    } elseif ($key -in @('-h','--help')) { Usage }
    else { Die "unknown argument '$key'" }
  }
  return $result
}
function Get-Field { param([IO.FileInfo]$File, [string]$Name)
  $pattern = "^${Name}: (.*)$"
  $line = Get-Content -LiteralPath $File.FullName | Where-Object { $_ -match $pattern } | Select-Object -First 1
  if ($null -eq $line) { return '' } else { return ($line -replace $pattern, '$1') }
}

function Emit { param([string]$EventType, [string[]]$Args)
  if ($EventType -notin @('claim','proposal','assessment','agreement','correction','handoff','release')) {
    Die "unknown event type '$EventType'"
  }
  $o = Parse-Options $Args
  Validate-Id 'session' $o.session; Validate-Id 'agent' $o.agent; Validate-Id 'issue' $o.issue
  Validate-Value 'paths' $o.paths; Validate-Value 'refs' $o.refs; Validate-Id 'option' $o.option
  Validate-Id 'selected' $o.selected; Validate-Id 'owner' $o.owner; Validate-Value 'participants' $o.participants
  if ($EventType -eq 'claim' -and $o.paths -eq 'none') { Die 'claim requires --paths' }
  if ($EventType -eq 'proposal' -and $o.option -eq 'none') { Die 'proposal requires --option' }
  if ($EventType -in @('assessment','correction','handoff','release') -and $o.refs -eq 'none') { Die "$EventType requires --refs" }
  if ($EventType -eq 'agreement') {
    if ($o.refs -eq 'none') { Die 'agreement requires --refs' }
    if ($o.selected -eq 'none') { Die 'agreement requires --selected' }
    if ($o.owner -eq 'none') { Die 'agreement requires --owner' }
    if ($o.participants -eq 'none') { Die 'agreement requires --participants' }
  }
  if ($o.bodyFile -and $o.body) { Die 'use either --body or --body-file, not both' }
  if ($o.bodyFile) {
    if (-not (Test-Path -LiteralPath $o.bodyFile -PathType Leaf)) { Die "body file not found: $($o.bodyFile)" }
    $body = Get-Content -LiteralPath $o.bodyFile -Raw
  } elseif ($o.body) { $body = $o.body }
  elseif ($EventType -eq 'claim') { $body = 'Intent and evidence: describe the intended change and why this scope is safe.' }
  else { Die "$EventType requires --body-file or --body with evidence and reasoning" }

  New-Item -ItemType Directory -Path $eventDir -Force | Out-Null
  $stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmss'Z'")
  $random = [Guid]::NewGuid().ToString('N').Substring(0, 8)
  $id = "$stamp-$($o.agent)-$random"
  $target = Join-Path $eventDir "$id.md"
  $temp = Join-Path $eventDir ".$id.$PID.tmp"
  $created = [DateTime]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
  $lines = @(
    '---', "id: $id", "type: $EventType", "session: $($o.session)", "agent: $($o.agent)",
    "created: $created", "issue: $($o.issue)", "paths: $($o.paths)", "refs: $($o.refs)",
    "option: $($o.option)", "selected: $($o.selected)", "owner: $($o.owner)",
    "participants: $($o.participants)", '---', '', $body.TrimEnd(), ''
  )
  Set-Content -LiteralPath $temp -Value ($lines -join "`n") -NoNewline
  Move-Item -LiteralPath $temp -Destination $target
  Say "created collaboration event: .context/memory/collaboration/events/$id.md"
  Say 'publish it in a separate chore(context): commit before changing the claimed product scope'
}

function Is-Released { param([string]$ClaimId, [IO.FileInfo[]]$Files)
  foreach ($file in $Files) {
    if ((Get-Field $file 'type') -in @('release','handoff') -and ",$(Get-Field $file 'refs')," -like "*,$ClaimId,*") { return $true }
  }
  return $false
}
function Overlap { param([string]$Left, [string]$Right)
  $l = $Left.Split(','); $r = $Right.Split(',')
  foreach ($a in $l) { foreach ($b in $r) { if ($a -ne 'none' -and $a -eq $b) { return $true } } }
  return $false
}
function Status { param([string[]]$Args)
  $o = Parse-Options $Args
  $files = @(Get-ChildItem -LiteralPath $eventDir -Filter '*.md' -File -ErrorAction SilentlyContinue)
  if ($files.Count -eq 0) { Say 'no collaboration events yet'; return }
  $files = @($files | Where-Object {
    ($o.session -eq '' -or (Get-Field $_ 'session') -eq $o.session) -and
    ($o.issue -eq '' -or (Get-Field $_ 'issue') -eq $o.issue)
  })
  Say "Collaboration events$(if ($o.session) { " for session $($o.session)" })$(if ($o.issue) { " / issue $($o.issue)" }):"
  foreach ($file in $files) {
    Say "- $(Get-Field $file 'type') $(Get-Field $file 'id') — agent=$(Get-Field $file 'agent') paths=$(Get-Field $file 'paths') refs=$(Get-Field $file 'refs')"
  }
  Say ''; Say 'Active claims and possible overlaps:'
  $claims = @($files | Where-Object { (Get-Field $_ 'type') -eq 'claim' -and -not (Is-Released (Get-Field $_ 'id') $files) })
  for ($a = 0; $a -lt $claims.Count; $a++) {
    $left = $claims[$a]
    Say "- $(Get-Field $left 'id') — agent=$(Get-Field $left 'agent') paths=$(Get-Field $left 'paths')"
    for ($b = $a + 1; $b -lt $claims.Count; $b++) {
      $right = $claims[$b]
      if ((Get-Field $left 'session') -eq (Get-Field $right 'session') -and (Get-Field $left 'issue') -eq (Get-Field $right 'issue') -and (Overlap (Get-Field $left 'paths') (Get-Field $right 'paths'))) {
        Say "  POSSIBLE OVERLAP with $(Get-Field $right 'id') — peers must assess and agree before either conflicting edit"
      }
    }
  }
  Say ''; Say 'Unresolved proposals/corrections require peer assessment and an agreement event before implementation.'
}

if ($Command -in @('', '-h', '--help', 'help')) { Usage }
switch ($Command) {
  'emit' {
    $emitArgs = @()
    if ($null -ne $Rest) { $emitArgs = @($Rest) }
    Emit $Type $emitArgs
  }
  'status' {
    $statusArgs = @()
    if ($Type) { $statusArgs += $Type }
    if ($null -ne $Rest) { $statusArgs += $Rest }
    Status $statusArgs
  }
  'check' {
    $checkArgs = @()
    if ($Type) { $checkArgs += $Type }
    if ($null -ne $Rest) { $checkArgs += $Rest }
    & (Join-Path $scriptDir 'context-collab-check.ps1') @checkArgs
    exit $LASTEXITCODE
  }
  default { Die "unknown command '$Command' (try: context-collab.ps1 help)" }
}
