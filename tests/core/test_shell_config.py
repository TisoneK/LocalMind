"""The shell commands run in is the user's choice: PowerShell, cmd or Git Bash on Windows; bash/zsh/... elsewhere."""

import pytest
from core import shell_config as sc
from core.config import settings


@pytest.fixture(autouse=True)
def _auto(monkeypatch):
    monkeypatch.setattr(settings, "localmind_shell", "auto", raising=False)


def test_windows_offers_powershell_cmd_and_git_bash(monkeypatch):
    found = {"pwsh": r"C:\Program Files\PowerShell\7\pwsh.exe", "powershell": r"C:\WINDOWS\powershell.exe"}
    monkeypatch.setattr(sc.shutil, "which", lambda n: found.get(n))
    monkeypatch.setenv("COMSPEC", r"C:\WINDOWS\system32\cmd.exe")
    monkeypatch.setattr(sc, "_git_bash_path", lambda: r"C:\Program Files\Git\bin\bash.exe")
    shells = {c.id: c for c in sc.detect_shells("win32")}
    assert set(shells) == {"powershell", "cmd", "git-bash"}
    assert shells["powershell"].path.endswith("pwsh.exe")  # PowerShell 7 preferred over the legacy one
    assert all(c.available for c in shells.values())


def test_missing_shells_are_listed_but_unavailable(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda n: None)
    monkeypatch.delenv("COMSPEC", raising=False)
    monkeypatch.setattr(sc, "_git_bash_path", lambda: "")
    assert not any(c.available for c in sc.detect_shells("win32"))


def test_unix_offers_bash_zsh_fish_sh(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda n: f"/bin/{n}" if n in ("bash", "sh") else None)
    shells = {c.id: c.available for c in sc.detect_shells("linux")}
    assert shells == {"bash": True, "zsh": False, "fish": False, "sh": True}


def test_auto_means_platform_default_and_unavailable_choice_falls_back(monkeypatch):
    assert sc.resolve("auto") is None
    monkeypatch.setattr(sc, "detect_shells", lambda platform=None: [sc.ShellChoice("zsh", "zsh", "", False)])
    assert sc.resolve("zsh") is None


def test_commands_are_wrapped_for_each_shell():
    ps = sc.ShellChoice("powershell", "PowerShell", "pwsh.exe", True)
    cmd = sc.ShellChoice("cmd", "Command Prompt (cmd)", "cmd.exe", True)
    gb = sc.ShellChoice("git-bash", "Git Bash", "bash.exe", True)
    assert sc.exec_args("Get-Date", ps) == ["pwsh.exe", "-NoProfile", "-NonInteractive", "-Command", "Get-Date"]
    assert sc.exec_args("dir", cmd) == ["cmd.exe", "/d", "/s", "/c", "dir"]
    assert sc.exec_args("ls -la", gb) == ["bash.exe", "-c", "ls -la"]


def test_the_agent_is_told_the_shell_only_when_one_was_chosen(monkeypatch):
    assert sc.note() == ""
    monkeypatch.setattr(settings, "localmind_shell", "bash", raising=False)
    monkeypatch.setattr(sc, "detect_shells", lambda platform=None: [sc.ShellChoice("bash", "bash", "/bin/bash", True)])
    assert "bash" in sc.note()


def test_the_shell_tool_really_runs_in_the_chosen_shell(monkeypatch):
    import shutil

    if not shutil.which("sh"):
        pytest.skip("no sh")
    from tools.shell import _run

    monkeypatch.setattr(settings, "localmind_shell", "sh", raising=False)
    out = _run("echo $0")
    assert out["success"]
    assert "sh" in str(out["message"])
