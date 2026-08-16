# Current Task

**Status:** done — Session 258: fixed two live Windows bugs. (1) Shell regression: the legacy `shell_exec` dispatch gate rejected every PowerShell cmdlet (`Get-ChildItem -Path $env:USERPROFILE\Desktop`) with `nl_dispatch_removed` — Case 2 now consults `_looks_like_powershell()` so cmdlets route to run_command. (2) Tool chaining: shell/file_write schemas + SHELL/FILE_WRITE workflows + Operator persona + universal FOLLOW-THROUGH rule now say "listing the folder is only step ONE — then call file_write" so the agent chains shell → file_write instead of stopping after the listing. Suite 1,802 pass (4 pre-existing env-gated shell fails). See review-48.

**Feature:** none
