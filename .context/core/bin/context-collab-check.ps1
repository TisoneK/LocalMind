#!/usr/bin/env pwsh
# context-collab-check.ps1 — Windows integration-readiness validator.

[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)] [string[]] $Arguments
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say { param([string]$Message) Write-Output $Message }
function Fail { param([string]$Message) $script:Failures++; [Console]::Error.WriteLine("context-collab: check: $Message") }
function Die { param([string]$Message) [Console]::Error.WriteLine("context-collab: $Message"); exit 2 }
function Usage {
  @(
    'context-collab check [--session ID] [--issue ID]',
    '',
    'Validates event metadata, references, agreements, overlaps, resolutions, and releases.',
    'Exit codes: 0 passed · 1 validation failure · 2 usage/error'
  ) | ForEach-Object { Say $_ }
  exit 2
}

$scriptDir = $PSScriptRoot
$coreDir = (Resolve-Path (Join-Path $scriptDir '..')).Path
$contextDir = Split-Path -Parent $coreDir
$eventDir = Join-Path $contextDir 'memory/collaboration/events'

function Get-Field { param([IO.FileInfo]$File, [string]$Name)
  $pattern = "^${Name}: (.*)$"
  $line = Get-Content -LiteralPath $File.FullName | Where-Object { $_ -match $pattern } | Select-Object -First 1
  if ($null -eq $line) { return '' } else { return ($line -replace $pattern, '$1') }
}
function Valid-Id { param([string]$Value) return ($Value -match '^[A-Za-z0-9._:-]+$') }
function Valid-Sha { param([string]$Value) return ($Value -match '^[0-9A-Fa-f]{7,40}$') }
function In-Scope { param([IO.FileInfo]$File)
  return (($script:Session -eq '' -or (Get-Field $File 'session') -eq $script:Session) -and
          ($script:Issue -eq '' -or (Get-Field $File 'issue') -eq $script:Issue))
}
function Event-By-Id { param([string]$Id)
  return @($script:Files | Where-Object { (Get-Field $_ 'id') -eq $Id } | Select-Object -First 1)
}
function Refs { param([IO.FileInfo]$File)
  $value = Get-Field $File 'refs'
  if ($value -eq 'none' -or $value -eq '') { return @() }
  return @($value.Split(',') | Where-Object { $_ -ne '' })
}
function Has-Ref-Type { param([IO.FileInfo]$File, [string]$Type)
  foreach ($ref in (Refs $File)) {
    $target = @(Event-By-Id $ref)
    if ($target.Count -gt 0 -and (Get-Field $target[0] 'type') -eq $Type) { return $true }
  }
  return $false
}
function Referenced-By-Type { param([string]$Id, [string]$Type)
  $target = @(Event-By-Id $Id)
  if ($target.Count -eq 0) { return $false }
  $session = Get-Field $target[0] 'session'; $issue = Get-Field $target[0] 'issue'
  foreach ($file in $script:Files) {
    if ((Get-Field $file 'type') -eq $Type -and
        (Get-Field $file 'session') -eq $session -and
        (Get-Field $file 'issue') -eq $issue -and
        (Refs $file) -contains $Id) { return $true }
  }
  return $false
}
function Has-NonEventRef { param([IO.FileInfo]$File)
  foreach ($ref in (Refs $File)) { if (@(Event-By-Id $ref).Count -eq 0 -and (Valid-Sha $ref)) { return $true } }
  return $false
}
function Claim-Closed { param([string]$Id)
  return (Referenced-By-Type $Id 'release' -or Referenced-By-Type $Id 'handoff')
}
function Csv-Contains { param([string]$Csv, [string]$Value)
  return ((',' + $Csv + ',') -like "*,$Value,*")
}
function Distinct-Count { param([string]$Csv)
  return @($Csv.Split(',') | Where-Object { $_ -and $_ -ne 'none' } | Sort-Object -Unique).Count
}
function Overlap { param([string]$Left, [string]$Right)
  $leftPaths = $Left.Split(','); $rightPaths = $Right.Split(',')
  foreach ($leftPath in $leftPaths) {
    if ($leftPath -ne 'none' -and $rightPaths -contains $leftPath) { return $true }
  }
  return $false
}

function Check-Event { param([IO.FileInfo]$File)
  if (-not (In-Scope $File)) { return }
  $id = Get-Field $File 'id'; $type = Get-Field $File 'type'
  foreach ($key in @('id','type','session','agent','created','issue','paths','refs','option','selected','owner','participants')) {
    if (-not (Get-Field $File $key)) { Fail "$($File.Name) is missing $key" }
  }
  if (-not (Valid-Id $id)) { Fail "$($File.Name) has invalid id '$id'" }
  if ($type -notin @('claim','proposal','assessment','agreement','correction','handoff','release')) {
    Fail "$($File.Name) has unknown type '$type'"; return
  }
  foreach ($ref in (Refs $File)) {
    $target = @(Event-By-Id $ref)
    if ($target.Count -gt 0) {
      if ((Get-Field $target[0] 'session') -ne (Get-Field $File 'session')) { Fail "$id references event $ref from another session" }
      if ((Get-Field $target[0] 'issue') -ne (Get-Field $File 'issue')) { Fail "$id references event $ref from another issue" }
    } elseif (-not (Valid-Sha $ref)) {
      Fail "$id has unknown reference '$ref' (expected an event ID or commit SHA)"
    }
  }
  switch ($type) {
    'claim' { if ((Get-Field $File 'paths') -eq 'none') { Fail "claim $id has no paths" } }
    'proposal' { if ((Get-Field $File 'option') -eq 'none') { Fail "proposal $id has no option" } }
    'assessment' { if (-not (Has-Ref-Type $File 'proposal')) { Fail "assessment $id does not reference a proposal" } }
    'agreement' {
      if (-not (Has-Ref-Type $File 'proposal')) { Fail "agreement $id does not reference a proposal" }
      if (-not (Has-Ref-Type $File 'assessment')) { Fail "agreement $id does not reference an assessment" }
      $selected = Get-Field $File 'selected'; $owner = Get-Field $File 'owner'; $participants = Get-Field $File 'participants'
      if ($selected -eq 'none') { Fail "agreement $id has no selected option" }
      if ($owner -eq 'none') { Fail "agreement $id has no owner" }
      if ($participants -eq 'none') { Fail "agreement $id has no participants" }
      if (-not (Csv-Contains $participants $owner)) { Fail "agreement $id owner is not a participant" }
      if ((Distinct-Count $participants) -lt 2) { Fail "agreement $id needs at least two distinct participants" }
      $selectedFound = $false
      foreach ($ref in (Refs $File)) {
        $target = @(Event-By-Id $ref)
        if ($target.Count -gt 0 -and (Get-Field $target[0] 'type') -eq 'proposal' -and (Get-Field $target[0] 'option') -eq $selected) { $selectedFound = $true }
      }
      if (-not $selectedFound) { Fail "agreement $id selects an option not present in its referenced proposals" }
    }
    'correction' { if (-not (Referenced-By-Type $id 'agreement')) { Fail "correction $id has no peer agreement" } }
    'handoff' {
      if (-not (Has-Ref-Type $File 'agreement')) { Fail "handoff $id does not reference an agreement" }
      if ((Get-Field $File 'owner') -eq 'none') { Fail "handoff $id has no receiving owner" }
    }
    'release' {
      if (-not (Has-Ref-Type $File 'claim') -and -not (Has-Ref-Type $File 'handoff')) { Fail "release $id does not reference a claim or handoff" }
      if (-not (Has-NonEventRef $File)) { Fail "release $id does not reference a product commit" }
    }
  }
}

function Check-Duplicates {
  for ($i = 0; $i -lt $script:Files.Count; $i++) {
    if (-not (In-Scope $script:Files[$i])) { continue }
    for ($j = 0; $j -lt $i; $j++) {
      if ((In-Scope $script:Files[$j]) -and (Get-Field $script:Files[$i] 'id') -eq (Get-Field $script:Files[$j] 'id')) {
        Fail "duplicate event id $(Get-Field $script:Files[$i] 'id')"
      }
    }
  }
}
function Check-Overlaps {
  $claims = @($script:Files | Where-Object { (In-Scope $_) -and (Get-Field $_ 'type') -eq 'claim' -and -not (Claim-Closed (Get-Field $_ 'id')) })
  for ($i = 0; $i -lt $claims.Count; $i++) {
    for ($j = $i + 1; $j -lt $claims.Count; $j++) {
      if ((Get-Field $claims[$i] 'session') -eq (Get-Field $claims[$j] 'session') -and
          (Get-Field $claims[$i] 'issue') -eq (Get-Field $claims[$j] 'issue') -and
          (Overlap (Get-Field $claims[$i] 'paths') (Get-Field $claims[$j] 'paths'))) {
        Fail "active claims overlap: $(Get-Field $claims[$i] 'id') and $(Get-Field $claims[$j] 'id')"
      }
    }
  }
}
function Check-Resolutions {
  foreach ($file in $script:Files) {
    if (-not (In-Scope $file)) { continue }
    $id = Get-Field $file 'id'; $type = Get-Field $file 'type'
    switch ($type) {
      'claim' { if (-not (Claim-Closed $id)) { Fail "claim $id is not released or handed off" } }
      { $_ -in @('proposal','assessment') } { if (-not (Referenced-By-Type $id 'agreement')) { Fail "$type $id is not resolved by an agreement" } }
      'handoff' { if (-not (Referenced-By-Type $id 'release')) { Fail "handoff $id is not released" } }
    }
  }
}

$script:Session = ''; $script:Issue = ''
$args = if ($null -eq $Arguments) { @() } else { @($Arguments) }
for ($i = 0; $i -lt $args.Count; $i++) {
  switch ($args[$i]) {
    '--session' { if ($i + 1 -ge $args.Count) { Die '--session needs a value' }; $script:Session = $args[++$i] }
    '--issue' { if ($i + 1 -ge $args.Count) { Die '--issue needs a value' }; $script:Issue = $args[++$i] }
    '-h' { Usage }
    '--help' { Usage }
    default { Die "unknown argument '$($args[$i])'" }
  }
}
if ($script:Session -and -not (Valid-Id $script:Session)) { Die "invalid session id: $($script:Session)" }
if ($script:Issue -and -not (Valid-Id $script:Issue)) { Die "invalid issue id: $($script:Issue)" }

$script:Files = @(Get-ChildItem -LiteralPath $eventDir -Filter '*.md' -File -ErrorAction SilentlyContinue)
if ($script:Files.Count -eq 0) { Say 'collaboration check: no events (nothing to check)'; exit 0 }
$script:Failures = 0
foreach ($file in $script:Files) { Check-Event $file }
Check-Duplicates
Check-Overlaps
Check-Resolutions
if ($script:Failures -gt 0) {
  [Console]::Error.WriteLine("context-collab: collaboration check failed: $($script:Failures) problem(s)")
  exit 1
}
Say "collaboration check passed: $($script:Files.Count) event(s), all claims resolved and agreements/releases complete"
