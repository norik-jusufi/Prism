"""PRISM integrated terminal.

A command runner, not a full terminal emulator: each command runs in a
fresh cmd.exe / PowerShell (or sh on other systems) in the session's working
directory, with output streamed back live. `cd`, `cls`/`clear` and
`exit` are handled here, so the working directory persists between commands.
Interactive full-screen programs (vim, htop) are not supported; anything
line-based works, including git, npm, pip, python, node and test runners.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, pyqtSignal

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
WIN = sys.platform == "win32"


class TerminalSession(QObject):
    output = pyqtSignal(str, str)      # text, stream ("out" | "err" | "sys")
    stateChanged = pyqtSignal(str)     # JSON-able summary handled by panel

    def __init__(self, cwd: str = "", shell: str = "cmd", parent=None) -> None:
        super().__init__(parent)
        start = Path(cwd).expanduser() if cwd else Path.home()
        self.cwd = str(start if start.is_dir() else Path.home())
        self.shell = shell if shell in ("cmd", "powershell") else "cmd"
        self.proc: QProcess | None = None
        self.command = ""

    # --- state
    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning

    def summary(self) -> dict:
        return {"cwd": self.cwd, "shell": self.shell, "running": self.running,
                "command": self.command if self.running else ""}

    def set_shell(self, shell: str) -> None:
        if shell in ("cmd", "powershell"):
            self.shell = shell
            self.stateChanged.emit("shell")

    # --- commands
    def run(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        if self.running:                # feed stdin of the running program
            self.proc.write((line + "\n").encode("utf-8"))
            self.output.emit(line + "\n", "in")
            return
        low = line.lower()
        if low in ("cls", "clear"):
            self.output.emit("", "clear")
            return
        if low == "exit":
            self.output.emit("", "close")
            return
        if re.match(r"^(cd|chdir)(\s|$)|^cd(\.\.|\\|/)", low) or (WIN and re.match(r"^[a-z]:$", low)):
            self._cd(line)
            return
        self._spawn(line)

    def _cd(self, line: str) -> None:
        if WIN and re.match(r"^[a-zA-Z]:$", line):
            target = line + "\\"
        else:
            target = re.sub(r"^(cd|chdir)\s*(/d\s+)?", "", line, flags=re.I).strip().strip('"')
        if not target:
            self.output.emit(self.cwd + "\n", "out")
            return
        path = Path(os.path.expandvars(os.path.expanduser(target)))
        if not path.is_absolute():
            path = Path(self.cwd) / path
        try:
            path = path.resolve()
        except OSError:
            pass
        if path.is_dir():
            self.cwd = str(path)
            self.stateChanged.emit("cwd")
        else:
            self.output.emit(f"The system cannot find the path specified: {target}\n", "err")

    def _spawn(self, line: str) -> None:
        proc = QProcess(self)
        proc.setWorkingDirectory(self.cwd)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("FORCE_COLOR", "0")
        env.insert("NO_COLOR", "1")
        env.insert("GIT_PAGER", "cat")
        env.insert("PAGER", "cat")
        env.insert("GIT_TERMINAL_PROMPT", "0")
        proc.setProcessEnvironment(env)
        proc.readyReadStandardOutput.connect(lambda p=proc: self._read(p, "out"))
        proc.readyReadStandardError.connect(lambda p=proc: self._read(p, "err"))
        proc.finished.connect(lambda code, _status, p=proc: self._done(p, code))
        proc.errorOccurred.connect(lambda err, p=proc: self._error(p, err))
        self.proc = proc
        self.command = line
        if WIN and self.shell == "powershell":
            proc.start("powershell.exe", ["-NoLogo", "-NoProfile", "-NonInteractive",
                                          "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + line])
        elif WIN:
            # chcp 65001 makes cmd builtins print UTF-8.
            proc.setNativeArguments(f'/d /s /c "chcp 65001>nul & {line}"')
            proc.start("cmd.exe", [])
        else:
            proc.start("/bin/sh", ["-c", line])
        self.stateChanged.emit("run")

    def _read(self, proc: QProcess, stream: str) -> None:
        data = proc.readAllStandardOutput() if stream == "out" else proc.readAllStandardError()
        text = bytes(data).decode("utf-8", errors="replace")
        if not text:
            return
        if "�" in text and WIN:       # not UTF-8: fall back to the OEM code page
            try:
                text = bytes(data).decode("oem", errors="replace")
            except LookupError:
                pass
        self.output.emit(ANSI.sub("", text).replace("\r\n", "\n"), stream)

    def _done(self, proc: QProcess, code: int) -> None:
        if proc is not self.proc:
            return
        self.proc = None
        self.output.emit(f"[exit {code}]\n" if code else "", "exit")
        self.stateChanged.emit("done")
        proc.deleteLater()

    def _error(self, proc: QProcess, err) -> None:
        if err == QProcess.ProcessError.FailedToStart and proc is self.proc:
            self.proc = None
            self.output.emit(f"Could not start the shell ({self.shell}).\n", "err")
            self.stateChanged.emit("done")

    def interrupt(self) -> None:
        if self.running:
            self.proc.kill()
            self.output.emit("^C\n", "sys")
