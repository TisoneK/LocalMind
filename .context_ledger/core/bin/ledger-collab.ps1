#!/usr/bin/env pwsh
# ledger-collab.ps1 -- PowerShell peer coordination helper.
#
# SOURCE ENCODING - pure ASCII, on purpose. Windows PowerShell 5.1 decodes a
# BOM-less script with the *system codepage*, not UTF-8, so a non-ASCII byte
# here can fail the parse there (an em-dash decodes to U+201D, which the
# parser reads as a string terminator) while pwsh 7 parses it fine. Emit a
# character the sh port writes as a literal from its code point instead -
# [char]0x2014 em-dash, [char]0x2026 ellipsis - so both ports emit the same
# bytes. Enforced by `ledger-sync verify` and tests/run-tests.sh; rationale
# in core/CHANGELOG.md (2.0.4).
#
# Coordination state is immutable, one-file-per-event under
# .context_ledger/memory/collaboration/events/. Product changes still belong on an
# isolated branch/worktree and are never merged by this helper.
#
# Events are JSON documents (schema: core/schemas/collab-event.schema.json)
# written in the same strict profile as the sh tool (one "key": value per
# line, UTF-8 without BOM) so both platforms produce identical bytes.
# Legacy markdown events (<id>.md) are still read by status and check.
#
# Usage:
#   .context_ledger/core/bin/ledger-collab.cmd emit claim `
#     --session ID --agent ID --issue ID --paths src/a.py `
#     --body-file C:\path\claim.md
#   .context_ledger/core/bin/ledger-collab.cmd status --session ID --issue ID
#   .context_ledger/core/bin/ledger-collab.cmd check --session ID --issue ID

[CmdletBinding()]
param(
  [Parameter(Position = 0)] [string] $Command = '',
  [Parameter(Position = 1)] [string] $Type = '',
  [Parameter(Position = 2, ValueFromRemainingArguments = $true)] [string[]] $Extra
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Say { param([string]$Message) Write-Output $Message }
function Die { param([string]$Message) [Console]::Error.WriteLine("ledger-collab: $Message"); exit 1 }
function Usage {
  @(
    'Commands:',
    '  emit TYPE --session ID --agent ID --issue ID [metadata] [--body-file FILE]',
    '  status [--session ID] [--issue ID]',
    '  check  [--session ID] [--issue ID]   integration-readiness gate',
    '  cohort open|list|status ...          pre-allocate codenames for siblings',
    '',
    'Metadata: --paths CSV --refs/--re CSV --option ID --selected ID --owner ID',
    '          --participants CSV --to CSV (note recipients) --body TEXT --body-file FILE',
    '',
    'Event types: note claim proposal assessment agreement correction handoff release',
    '  note -- the office channel: an informal heads-up to peers. Only a body',
    '         is required; never gates integration. The proposal/assessment/',
    '         agreement ceremony is reserved for a genuine conflict.'
  ) | ForEach-Object { Say $_ }
  exit 2
}

$scriptDir = $PSScriptRoot
$coreDir = (Resolve-Path (Join-Path $scriptDir '..')).Path
$ledgerDir = Split-Path -Parent $coreDir
$eventDir = Join-Path $ledgerDir 'memory/collaboration/events'
$officeDir = Join-Path $ledgerDir 'memory/office'
$historyDir = Join-Path $ledgerDir 'history'
$archiveDir = Join-Path $ledgerDir 'archive'

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
# NOTE: never name a PowerShell parameter $Args - it collides with the
# automatic variable of the same name, and flag tokens (--session ...)
# are silently lost before the loop ever sees them.
function Parse-Options { param([string[]]$OptArgs)
  $result = @{
    session = ''; agent = ''; issue = ''; paths = 'none'; refs = 'none'; option = 'none'
    selected = 'none'; owner = 'none'; participants = 'none'; body = ''; bodyFile = ''
  }
  for ($i = 0; $i -lt $OptArgs.Count; $i++) {
    $key = $OptArgs[$i]
    if ($key -in @('--session','--agent','--issue','--paths','--refs','--re','--option','--selected','--owner','--participants','--to','--body','--body-file')) {
      if ($i + 1 -ge $OptArgs.Count) { Die "$key needs a value" }
      $name = switch ($key) {
        '--body-file' { 'bodyFile' }
        '--re' { 'refs' }        # informal alias, mainly for notes
        '--to' { 'participants' } # a note's addressed peer(s)
        default { $key.Substring(2) }
      }
      $result[$name] = $OptArgs[$i + 1]; $i++
    } elseif ($key -in @('-h','--help')) { Usage }
    else { Die "unknown argument '$key'" }
  }
  return $result
}
function ConvertTo-JsonEscaped { param([string]$Text)
  # Backslash first, then quote, then the escapable control chars.
  return $Text.Replace('\', '\\').Replace('"', '\"').Replace("`t", '\t').Replace("`r", '\r').Replace("`n", '\n')
}
function ConvertTo-JsonArray { param([string]$Csv)
  if (-not $Csv -or $Csv -eq 'none') { return '[]' }
  $items = @($Csv -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | ForEach-Object { '"' + (ConvertTo-JsonEscaped $_) + '"' })
  if ($items.Count -eq 0) { return '[]' }
  return '[' + ($items -join ', ') + ']'
}
function ConvertTo-JsonScalar { param([string]$Value)
  if (-not $Value -or $Value -eq 'none') { return 'null' }
  return '"' + (ConvertTo-JsonEscaped $Value) + '"'
}
function Test-JsonFile { param([IO.FileInfo]$File)
  $first = [IO.File]::ReadLines($File.FullName) | Select-Object -First 1
  return ($null -ne $first -and $first.TrimEnd("`r") -match '^\{')
}
# JSON value -> the same field value the markdown parser produces:
# null/[] -> 'none', arrays -> comma-joined, strings -> unescaped.
function Get-JsonField { param([IO.FileInfo]$File, [string]$Name)
  $obj = [IO.File]::ReadAllText($File.FullName) | ConvertFrom-Json
  $prop = $obj.PSObject.Properties[$Name]
  if ($null -eq $prop) { return '' }
  if ($null -eq $prop.Value) { return 'none' }
  if ($prop.Value -is [System.Array]) {
    if ($prop.Value.Count -eq 0) { return 'none' }
    return (@($prop.Value | ForEach-Object { [string]$_ }) -join ',')
  }
  return [string]$prop.Value
}
function Get-Field { param([IO.FileInfo]$File, [string]$Name)
  if (Test-JsonFile $File) { return Get-JsonField $File $Name }
  $pattern = "^${Name}: (.*)$"
  $line = Get-Content -Encoding UTF8 -LiteralPath $File.FullName | Where-Object { $_ -match $pattern } | Select-Object -First 1
  if ($null -eq $line) { return '' } else { return (($line -replace $pattern, '$1').TrimEnd("`r")) }
}
# First non-empty body line, for the chatter feed.
function Get-FirstBodyLine { param([IO.FileInfo]$File)
  if (Test-JsonFile $File) {
    $body = Get-JsonField $File 'body'
    if ($body -eq 'none' -or $body -eq '') { return '' }
    foreach ($ln in ($body -split "`n")) { if ($ln.Trim() -ne '') { return $ln } }
    return ''
  }
  $dashes = 0
  foreach ($raw in Get-Content -Encoding UTF8 -LiteralPath $File.FullName) {
    $ln = $raw.TrimEnd("`r")
    if ($ln -eq '---') { $dashes++; continue }
    if ($dashes -ge 2 -and $ln.Trim() -ne '') { return $ln }
  }
  return ''
}

function Emit { param([string]$EventType, [string[]]$EventArgs)
  if ($EventType -notin @('note','claim','proposal','assessment','agreement','correction','handoff','release','cohort')) {
    Die "unknown event type '$EventType'"
  }
  $o = Parse-Options $EventArgs
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
  if ($EventType -eq 'cohort' -and $o.participants -eq 'none') { Die 'cohort requires --participants (the reserved codenames)' }
  if ($o.bodyFile -and $o.body) { Die 'use either --body or --body-file, not both' }
  if ($o.bodyFile) {
    if (-not (Test-Path -LiteralPath $o.bodyFile -PathType Leaf)) { Die "body file not found: $($o.bodyFile)" }
    $body = Get-Content -Encoding UTF8 -LiteralPath $o.bodyFile -Raw
  } elseif ($o.body) { $body = $o.body }
  elseif ($EventType -eq 'claim') { $body = 'Intent and evidence: describe the intended change and why this scope is safe.' }
  elseif ($EventType -eq 'cohort') { $body = 'Sibling cohort: codenames pre-allocated together so the wave cannot race the board.' }
  elseif ($EventType -eq 'note') { Die 'note requires --body or --body-file -- say what you want your peers to know' }
  else { Die "$EventType requires --body-file or --body with evidence and reasoning" }

  New-Item -ItemType Directory -Path $eventDir -Force | Out-Null
  $stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmss'Z'")
  $random = [Guid]::NewGuid().ToString('N').Substring(0, 8)
  $id = "$stamp-$($o.agent)-$random"
  $target = Join-Path $eventDir "$id.json"
  $temp = Join-Path $eventDir ".$id.$PID.tmp"
  $created = [DateTime]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
  $body = $body.TrimEnd("`r", "`n")
  if ($body -match '[\x00-\x08\x0B\x0C\x0E-\x1F]') {
    Die 'body contains control characters (tab, newline, and CR are the only ones allowed)'
  }
  # Strict profile: fixed key order, one "key": value per line, UTF-8
  # without BOM - byte-compatible with the sh writer.
  $json = @(
    '{',
    '  "schema": 1,',
    "  `"id`": `"$id`",",
    "  `"type`": `"$EventType`",",
    "  `"session`": `"$($o.session)`",",
    "  `"agent`": `"$($o.agent)`",",
    "  `"created`": `"$created`",",
    "  `"issue`": `"$($o.issue)`",",
    "  `"body`": `"$(ConvertTo-JsonEscaped $body)`",",
    "  `"paths`": $(ConvertTo-JsonArray $o.paths),",
    "  `"refs`": $(ConvertTo-JsonArray $o.refs),",
    "  `"option`": $(ConvertTo-JsonScalar $o.option),",
    "  `"selected`": $(ConvertTo-JsonScalar $o.selected),",
    "  `"owner`": $(ConvertTo-JsonScalar $o.owner),",
    "  `"participants`": $(ConvertTo-JsonArray $o.participants)",
    '}'
  ) -join "`n"
  # WriteAllText: UTF-8 without BOM (a BOM would break the sh reader).
  [IO.File]::WriteAllText($temp, $json)
  Move-Item -LiteralPath $temp -Destination $target
  Say "created collaboration event: .context_ledger/memory/collaboration/events/$id.json"
  if ($EventType -eq 'note') {
    Say 'publish it in a chore(ledger): commit so your peers see it -- a note carries no obligation'
  } elseif ($EventType -eq 'cohort') {
    # Cohort-Open prints the full commit + spawn-brief guidance itself.
  } else {
    Say 'publish it in a separate chore(ledger): commit before changing the claimed product scope'
  }
}

function Is-Released { param([IO.FileInfo]$ClaimFile, [IO.FileInfo[]]$Files)
  $cid = Get-Field $ClaimFile 'id'
  $cses = Get-Field $ClaimFile 'session'; $ciss = Get-Field $ClaimFile 'issue'
  $cpaths = Get-Field $ClaimFile 'paths'
  foreach ($file in $Files) {
    if ((Get-Field $file 'type') -notin @('release','handoff')) { continue }
    # (a) explicit event-ID linkage
    if (",$(Get-Field $file 'refs')," -like "*,$cid,*") { return $true }
    # (b) weak-agent fallback: SHA-only release/handoff that shares this
    #     claim's session+issue and overlaps its paths still closes it.
    if ((Get-Field $file 'session') -eq $cses -and (Get-Field $file 'issue') -eq $ciss -and
        (Overlap $cpaths (Get-Field $file 'paths'))) { return $true }
  }
  return $false
}
function Overlap { param([string]$Left, [string]$Right)
  $l = $Left.Split(','); $r = $Right.Split(',')
  foreach ($a in $l) { foreach ($b in $r) { if ($a -ne 'none' -and $a -eq $b) { return $true } } }
  return $false
}
function Status { param([string[]]$StatusArgs)
  $o = Parse-Options $StatusArgs
  $files = @(Get-ChildItem -LiteralPath $eventDir -File -ErrorAction SilentlyContinue |
    Where-Object { $_ -and ($_.Extension -eq '.md' -or $_.Extension -eq '.json') })
  if ($files.Count -eq 0) { Say 'no collaboration events yet'; return }
  $files = @($files | Where-Object {
    ($o.session -eq '' -or (Get-Field $_ 'session') -eq $o.session) -and
    ($o.issue -eq '' -or (Get-Field $_ 'issue') -eq $o.issue)
  })
  Say "Collaboration events$(if ($o.session) { " for session $($o.session)" })$(if ($o.issue) { " / issue $($o.issue)" }):"
  foreach ($file in $files) {
    Say "- $(Get-Field $file 'type') $(Get-Field $file 'id') -- agent=$(Get-Field $file 'agent') paths=$(Get-Field $file 'paths') refs=$(Get-Field $file 'refs')"
  }
  Say ''; Say 'Active claims and possible overlaps:'
  $claims = @($files | Where-Object { (Get-Field $_ 'type') -eq 'claim' -and -not (Is-Released $_ $files) })
  for ($a = 0; $a -lt $claims.Count; $a++) {
    $left = $claims[$a]
    Say "- $(Get-Field $left 'id') -- agent=$(Get-Field $left 'agent') paths=$(Get-Field $left 'paths')"
    for ($b = $a + 1; $b -lt $claims.Count; $b++) {
      $right = $claims[$b]
      if ((Get-Field $left 'session') -eq (Get-Field $right 'session') -and (Get-Field $left 'issue') -eq (Get-Field $right 'issue') -and (Overlap (Get-Field $left 'paths') (Get-Field $right 'paths'))) {
        Say "  POSSIBLE OVERLAP with $(Get-Field $right 'id') -- talk it through (a note), compare the two changes, and agree who takes it"
      }
    }
  }
  Say ''; Say 'Recent chatter (notes) -- read these first to catch up, like a team channel:'
  $notes = @($files | Where-Object { (Get-Field $_ 'type') -eq 'note' })
  if ($notes.Count -eq 0) {
    Say "  (none yet -- a quick 'note' is how you say what you're on or flag something to a peer)"
  } else {
    foreach ($n in $notes) {
      $to = Get-Field $n 'participants'; if ($to -eq 'none') { $to = '' }
      $re = Get-Field $n 'refs'; if ($re -eq 'none') { $re = '' }
      $arrow = if ($to) { " ->$to" } else { '' }
      $reSuffix = if ($re) { "  (re: $re)" } else { '' }
      Say "- $(Get-Field $n 'agent')${arrow}: $(Get-FirstBodyLine $n)$reSuffix"
    }
  }
  Say ''
  Say 'A genuine conflict (same paths, incompatible changes) escalates to proposal -> assessment -> agreement.'
  Say "Everything else is a note plus your own claim/release -- you're on the same team, not bidding against each other."
}

# --- Sibling cohorts: pre-allocated codenames ---------------------------
# A cohort is a wave of sibling agents a parent spawns together. The ledger
# otherwise models serial arrival, so N siblings scanning the same board at
# once race for one codename. 'cohort open' reserves a contiguous block up
# front in ONE write (a reserved roster row per member + one cohort event);
# each sibling is handed its codename and claims its reserved row in place at
# check-in instead of scanning. See ledger-schema.md -> 'Sibling cohorts'.
function Cohort-Usage {
  @(
    'ledger-collab cohort -- pre-allocate codenames for a wave of sibling agents',
    '',
    '  open --count N [--agent NAME] [--task TEXT] [--cohort ID] [--session ID]',
    '        reserve N contiguous codenames: a reserved roster row per member',
    '        + one cohort event. Commit both, push, THEN spawn the siblings.',
    '  list  list recorded cohorts and their members.',
    '  status [--cohort ID]  each member codename and its current board state.',
    '',
    'Exit codes: 0 ok; 2 usage/error'
  ) | ForEach-Object { Say $_ }
  exit 2
}
# current office number = (highest frozen office on record) + 1. Mirrors the
# sh cohort_office_num / ledger-history max_office_num; records are permanent.
function Get-CohortOfficeNum {
  $max = 0
  $globs = @((Join-Path $historyDir 'office-*.md'), (Join-Path $historyDir 'office-*'), (Join-Path $archiveDir 'office-*.tar.gz'))
  foreach ($g in $globs) {
    foreach ($p in (Get-ChildItem -Path $g -ErrorAction SilentlyContinue)) {
      $b = $p.BaseName -replace '\..*$', ''
      if ($b -match '^office-0*([0-9]+)$') { $n = [int]$Matches[1]; if ($n -gt $max) { $max = $n } }
    }
  }
  return ($max + 1)
}
# highest session number on the board or in the duty log, reading the session
# number out of BOTH codename forms: legacy S<n> and structured OF<oo>SS<n>.
function Get-CohortNextNum {
  $roster = Join-Path $officeDir 'agents/roster.md'
  $sessions = Join-Path $officeDir 'agents/sessions.md'
  $max = 0
  if (Test-Path -LiteralPath $roster) {
    foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $roster) {
      if ($line -notmatch '^\s*\|') { continue }
      $cells = $line -split '\|'
      if ($cells.Count -lt 4) { continue }
      $code = $cells[2].Trim()
      if ($code -match '^[Ss]([0-9]+)$') { $n = [int]$Matches[1]; if ($n -gt $max) { $max = $n } }
      elseif ($code -match '^OF[0-9]+SS([0-9]+)$') { $n = [int]$Matches[1]; if ($n -gt $max) { $max = $n } }
    }
  }
  if (Test-Path -LiteralPath $sessions) {
    foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $sessions) {
      if ($line -match '^##\s.*[Ss]ession\s+([0-9]+)') { $n = [int]$Matches[1]; if ($n -gt $max) { $max = $n } }
    }
  }
  return ($max + 1)
}
function Get-CohortRosterRow { param([string]$Roster, [string]$Want)
  if (-not (Test-Path -LiteralPath $Roster)) { return '' }
  foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $Roster) {
    if ($line -notmatch '^\s*\|') { continue }
    $cells = $line -split '\|'
    if ($cells.Count -lt 6) { continue }
    if ($cells[2].Trim().ToLower() -eq $Want.ToLower()) {
      return "$($cells[1].Trim()) [$($cells[5].Trim())]"
    }
  }
  return ''
}
function Cohort-Open { param([string[]]$OptArgs)
  $count = ''; $agent = 'parent'; $task = ''; $cohort = ''; $session = ''
  for ($i = 0; $i -lt $OptArgs.Count; $i++) {
    switch ($OptArgs[$i]) {
      '--count'   { if ($i+1 -ge $OptArgs.Count) { Die '--count needs a value' }; $count = $OptArgs[++$i] }
      '--agent'   { if ($i+1 -ge $OptArgs.Count) { Die '--agent needs a value' }; $agent = $OptArgs[++$i] }
      '--task'    { if ($i+1 -ge $OptArgs.Count) { Die '--task needs a value' }; $task = $OptArgs[++$i] }
      '--cohort'  { if ($i+1 -ge $OptArgs.Count) { Die '--cohort needs a value' }; $cohort = $OptArgs[++$i] }
      '--session' { if ($i+1 -ge $OptArgs.Count) { Die '--session needs a value' }; $session = $OptArgs[++$i] }
      '-h'        { Cohort-Usage }
      '--help'    { Cohort-Usage }
      default     { Die "unknown argument '$($OptArgs[$i])' (try: ledger-collab cohort --help)" }
    }
  }
  if ($count -notmatch '^[0-9]+$') { Die 'cohort open requires --count N (a positive integer)' }
  $countN = [int]$count
  if ($countN -lt 1) { Die '--count must be at least 1' }
  if ($countN -gt 50) { Die "--count $countN is implausibly large (cap 50) -- split the dispatch" }
  Validate-Id 'agent' $agent
  if (-not $task) { $task = '(unspecified)' }
  $roster = Join-Path $officeDir 'agents/roster.md'
  if (-not (Test-Path -LiteralPath $roster)) { Die "no roster at $roster -- is this a bootstrapped project?" }
  if (-not $cohort) { $cohort = 'C-' + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmss'Z'") }
  Validate-Id 'cohort' $cohort
  $base = Get-CohortNextNum
  $office = Get-CohortOfficeNum
  # structured OF<oo>SS<ss> codename: office + session, globally unique
  # (legacy S<NNN> still accepted everywhere).
  $codesArr = @(); for ($k = 0; $k -lt $countN; $k++) { $codesArr += ('OF{0:D2}SS{1:D2}' -f $office, ($base + $k)) }
  $codes = $codesArr -join ','
  # append one reserved roster row per member, after the last table row
  $lines = @(Get-Content -Encoding UTF8 -LiteralPath $roster)
  $lastIdx = -1
  for ($j = 0; $j -lt $lines.Count; $j++) { if ($lines[$j] -match '^\s*\|') { $lastIdx = $j } }
  $rows = @()
  for ($s = 1; $s -le $countN; $s++) {
    $rows += "| (cohort $cohort slot $s) | $($codesArr[$s-1]) | - | reserved - cohort $cohort ($s/$countN) | Reserved | opened by $agent for: $task; the assigned sibling claims this row in place at check-in |"
  }
  if ($lastIdx -ge 0) {
    $out = @(); for ($j = 0; $j -lt $lines.Count; $j++) { $out += $lines[$j]; if ($j -eq $lastIdx) { $out += $rows } }
  } else { $out = @($lines + $rows) }
  [IO.File]::WriteAllText($roster, (($out -join "`n") + "`n"))
  # record the cohort as one immutable event (attribution + member list)
  $sess = if ($session) { $session } else { $cohort }
  Emit 'cohort' @('--agent', $agent, '--session', $sess, '--issue', $cohort, '--participants', $codes, '--body', $task)
  Say ''
  Say "cohort $cohort -- reserved $countN codename(s): $codes"
  Say 'Reserved roster rows written; cohort event recorded. Commit BOTH ledger surfaces in one chore(ledger): commit, push, THEN spawn the siblings:'
  Say '  git add .context_ledger/memory/office/agents/roster.md .context_ledger/memory/collaboration/events/'
  Say "  git commit -m `"chore(ledger): open cohort $cohort -- reserve $codes`" && git push"
  Say 'If the push is rejected a peer checked in meanwhile: revert the rows (git checkout -- the roster) and re-run -- one re-read, not N.'
  Say ''
  Say 'Hand each sibling ONE codename in its spawn brief:'
  foreach ($c in $codesArr) {
    Say "  - `"You are <pick a real name>, codename $c, cohort $cohort. Read .context_ledger/kickoff.md and follow it. At check-in, CLAIM the reserved row for $c in the roster IN PLACE (your name + Status Working) -- do NOT scan for a free number.`""
  }
}
function Cohort-List {
  $files = @(Get-ChildItem -LiteralPath $eventDir -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -eq '.json' })
  $n = 0
  foreach ($f in $files) {
    if ((Get-Field $f 'type') -ne 'cohort') { continue }
    $n++
    Say "- $(Get-Field $f 'issue') -- opened by $(Get-Field $f 'agent') -- members: $(Get-Field $f 'participants')"
    $body = Get-FirstBodyLine $f; if ($body) { Say "    task: $body" }
  }
  if ($n -eq 0) { Say '(none)' }
}
function Cohort-Status { param([string[]]$OptArgs)
  $id = ''
  for ($i = 0; $i -lt $OptArgs.Count; $i++) {
    switch ($OptArgs[$i]) {
      '--cohort' { if ($i+1 -ge $OptArgs.Count) { Die '--cohort needs a value' }; $id = $OptArgs[++$i] }
      '-h'       { Cohort-Usage }
      '--help'   { Cohort-Usage }
      default    { Die "unknown argument '$($OptArgs[$i])'" }
    }
  }
  $roster = Join-Path $officeDir 'agents/roster.md'
  $files = @(Get-ChildItem -LiteralPath $eventDir -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -eq '.json' })
  $n = 0
  foreach ($f in $files) {
    if ((Get-Field $f 'type') -ne 'cohort') { continue }
    $ci = Get-Field $f 'issue'
    if ($id -and $ci -ne $id) { continue }
    $n++
    Say "cohort $ci -- opened by $(Get-Field $f 'agent')"
    foreach ($c in (($(Get-Field $f 'participants')) -split ',')) {
      $c = $c.Trim(); if (-not $c) { continue }
      $row = Get-CohortRosterRow $roster $c
      if (-not $row) { Say "  $c -- (not on the board -- clocked out, or never claimed)" }
      else { Say "  $c -- $row" }
    }
  }
  if ($n -eq 0) { Say '(no matching cohort)' }
}

if ($Command -in @('', '-h', '--help', 'help')) { Usage }
switch ($Command) {
  'emit' {
    $emitArgs = @()
    if ($null -ne $Extra) { $emitArgs = @($Extra) }
    Emit $Type $emitArgs
  }
  'status' {
    $statusArgs = @()
    if ($Type) { $statusArgs += $Type }
    if ($null -ne $Extra) { $statusArgs += $Extra }
    Status $statusArgs
  }
  'cohort' {
    $sub = $Type
    $subArgs = @()
    if ($null -ne $Extra) { $subArgs = @($Extra) }
    switch ($sub) {
      'open'   { Cohort-Open $subArgs }
      'list'   { Cohort-List }
      'status' { Cohort-Status $subArgs }
      { $_ -in @('', '-h', '--help', 'help') } { Cohort-Usage }
      default  { Die "unknown cohort subcommand '$sub' (try: ledger-collab cohort --help)" }
    }
  }
  'check' {
    $checkArgs = @()
    if ($Type) { $checkArgs += $Type }
    if ($null -ne $Extra) { $checkArgs += $Extra }
    # A child .ps1's `exit N` does not reliably set $LASTEXITCODE on every
    # host (reading it unset trips StrictMode), so pre-seed it and fall
    # back to the child's success status.
    $global:LASTEXITCODE = $null
    & (Join-Path $scriptDir 'ledger-collab-check.ps1') @checkArgs
    if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }
    if ($?) { exit 0 } else { exit 1 }
  }
  default { Die "unknown command '$Command' (try: ledger-collab.ps1 help)" }
}
