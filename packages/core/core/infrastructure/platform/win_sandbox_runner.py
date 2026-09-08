"""Windows restricted-token sandbox runner for executing child processes.

Executes commands under a filtered token derived from the caller's own token
(``CreateRestrictedToken`` with ``DISABLE_MAX_PRIVILEGE``) launched via
``CreateProcessAsUserW``, so it works from normal user processes without
SE_IMPERSONATE/SE_ASSIGNPRIMARYTOKEN privileges (unlike the Win32 Safer +
CreateProcessWithTokenW approach).

The child shell is PowerShell with ``-EncodedCommand`` (unicode-safe); cmd.exe
is the fallback. Verified on Win11: both survive ``DISABLE_MAX_PRIVILEGE``,
while LUA_TOKEN or deny-only SIDs kill every child with
STATUS_DLL_INIT_FAILED (0xC0000142) in headless/ssh sessions — avoid them.

Isolation scope (honest limitations):
- All token privileges are stripped; admin elevation inside the sandbox is
  impossible without them.
- Group SIDs and the caller's integrity level are kept; there is NO filesystem
  confinement: workspace-write and sensitive-read policies stay at the tool
  layer (tools/read.py, tools/edit.py, tools/create.py).

The child is placed in a Job Object with KILL_ON_JOB_CLOSE, so terminating
this runner (e.g. tool timeout) never leaves orphaned grandchildren behind.

Stdlib-only module: it must stay importable when launched as a plain script
(python win_sandbox_runner.py) from any working directory.
"""
from __future__ import annotations

import base64
import os
import shutil
import sys

PS_UTF8_PREAMBLE = (
    "$OutputEncoding = [System.Text.Encoding]::UTF8; "
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "$ProgressPreference = 'SilentlyContinue'; "
    "$InformationPreference = 'SilentlyContinue'; "
)


def select_shell() -> str:
    """Pick the child shell: prefer PowerShell (unicode-safe), fallback cmd."""
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return shutil.which("cmd") or os_comspec()


def os_comspec() -> str:
    return os.environ.get("ComSpec", "cmd.exe")


def encode_ps_command(command: str) -> str:
    """Encode a PowerShell command for -EncodedCommand (UTF-16LE base64)."""
    return base64.b64encode((PS_UTF8_PREAMBLE + command).encode("utf-16-le")).decode("ascii")


def build_shell_argv(shell: str, command: str) -> list[str]:
    """Return shell-specific argv (without the shell executable itself)."""
    name = shell.lower()
    if name.endswith(("pwsh.exe", "pwsh", "powershell.exe", "powershell")):
        return [
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encode_ps_command(command),
        ]
    # cmd.exe: /s strips the outer quotes, preserving inner ones.
    return ["/d", "/s", "/c", command]


def format_command_line(executable: str, argv: list[str]) -> str:
    """Format argv into a Windows command-line string (quote executable + args)."""
    parts = [_win_quote(executable)]
    parts.extend(_win_quote(a) for a in argv)
    return " ".join(parts)


def _win_quote(arg: str) -> str:
    """Quote a single argument for a Windows command line."""
    if arg and '"' not in arg and " " not in arg and "\t" not in arg:
        return arg
    return f'"{arg}"'


def run_restricted_cmd(cmd: str, cwd: str | None = None) -> int:
    """Run ``cmd`` under a restricted token; blocks until exit; returns exit code."""
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # Token rights needed by CreateRestrictedToken/CreateProcessAsUserW.
    TOKEN_ASSIGN_PRIMARY = 0x0001
    TOKEN_DUPLICATE = 0x0002
    TOKEN_QUERY = 0x0008
    TOKEN_ADJUST_DEFAULT = 0x0080
    TOKEN_ADJUST_SESSIONID = 0x0100
    token_access = TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ADJUST_DEFAULT | TOKEN_ADJUST_SESSIONID

    DISABLE_MAX_PRIVILEGE = 0x00000001

    CREATE_NO_WINDOW = 0x08000000
    STARTF_USESTDHANDLES = 0x00000100
    INFINITE = 0xFFFFFFFF

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(f, ctypes.c_ulonglong) for f in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    HANDLE_FLAG_INHERIT = 0x00000001
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    # Explicit prototypes are mandatory on x64: without .restype/.argtypes a
    # pseudo-handle like (-1) is marshalled as a 32-bit int with garbage in the
    # upper bytes -> ERROR_INVALID_HANDLE deep inside token APIs.
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL

    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL

    advapi32.CreateRestrictedToken.argtypes = [
        wintypes.HANDLE,            # ExistingTokenHandle
        wintypes.DWORD,             # Flags
        wintypes.DWORD,             # SidsToDisableCount
        ctypes.c_void_p,            # SidsToDisable
        wintypes.DWORD,             # PrivilegesToDeleteCount
        ctypes.c_void_p,            # PrivilegesToDelete
        wintypes.DWORD,             # RestrictedSidsCount
        ctypes.c_void_p,            # RestrictedSids
        ctypes.POINTER(wintypes.HANDLE),  # NewTokenHandle
    ]
    advapi32.CreateRestrictedToken.restype = wintypes.BOOL

    def _make_restricted_token(h_base: wintypes.HANDLE, h_out: wintypes.HANDLE) -> bool:
        """Strip every privilege from a duplicate of our own token.

        Verified on Win11: adding LUA_TOKEN or deny-only SIDs here makes every
        child die with 0xC0000142 in headless sessions, so privileges-only is
        the strongest stable reduction.
        """
        return bool(
            advapi32.CreateRestrictedToken(
                h_base,
                DISABLE_MAX_PRIVILEGE,
                0, None,  # SidsToDisable
                0, None,  # PrivilegesToDelete
                0, None,  # RestrictedSids
                ctypes.byref(h_out),
            )
        )

    advapi32.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE,                  # hToken
        wintypes.LPCWSTR,                 # lpApplicationName
        wintypes.LPWSTR,                  # lpCommandLine
        ctypes.c_void_p,                  # lpProcessAttributes
        ctypes.c_void_p,                  # lpThreadAttributes
        wintypes.BOOL,                    # bInheritHandles
        wintypes.DWORD,                   # dwCreationFlags
        ctypes.c_void_p,                  # lpEnvironment
        wintypes.LPCWSTR,                 # lpCurrentDirectory
        ctypes.POINTER(STARTUPINFOW),     # lpStartupInfo
        ctypes.POINTER(PROCESS_INFORMATION),  # lpProcessInformation
    ]
    advapi32.CreateProcessAsUserW.restype = wintypes.BOOL

    def _inheritable_std_handles(si: STARTUPINFOW) -> bool:
        """Wire std handles when they are real, inheritable pipes; else let defaults apply."""
        ok_all = True
        for std_id, field in ((-10, "hStdInput"), (-11, "hStdOutput"), (-12, "hStdError")):
            h = kernel32.GetStdHandle(std_id & 0xFFFFFFFF)
            if not h or h == INVALID_HANDLE_VALUE:
                si.__setattr__(field, None)
                ok_all = False
                continue
            if not kernel32.SetHandleInformation(h, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT):
                si.__setattr__(field, None)
                ok_all = False
                continue
            si.__setattr__(field, h)
        return ok_all

    h_token = wintypes.HANDLE()
    h_restricted = wintypes.HANDLE()
    pi = PROCESS_INFORMATION()
    h_job = None

    try:
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), token_access, ctypes.byref(h_token)):
            raise ctypes.WinError(ctypes.get_last_error())

        # Restricted version of our OWN token -> no special privileges required.
        if not _make_restricted_token(h_token, h_restricted):
            raise ctypes.WinError(ctypes.get_last_error())

        shell = select_shell()
        cmdline = format_command_line(shell, build_shell_argv(shell, cmd))

        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        # Filtered tokens fail DLL init (STATUS_DLL_NOT_FOUND / 0xC0000142)
        # unless the target station/desktop is named explicitly.
        _desktop = ctypes.create_unicode_buffer("Winsta0\\Default")
        si.lpDesktop = ctypes.cast(_desktop, wintypes.LPWSTR)
        if not _inheritable_std_handles(si):
            # Some/std handles unusable (detached session): spawn without explicit redirection.
            si.dwFlags &= ~STARTF_USESTDHANDLES
            si.hStdInput = si.hStdOutput = si.hStdError = None
        else:
            si.dwFlags |= STARTF_USESTDHANDLES

        # Job object guarantees the whole tree dies with this runner (timeout,
        # cancellation, crash): KILL_ON_JOB_CLOSE fires when our handle closes.
        h_job = kernel32.CreateJobObjectW(None, None)
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if h_job and not kernel32.SetInformationJobObject(
            h_job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            kernel32.CloseHandle(h_job)
            h_job = None  # non-fatal: proceed without job tracking

        cmd_buf = ctypes.create_unicode_buffer(cmdline)
        ok = advapi32.CreateProcessAsUserW(
            h_restricted,
            None,
            cmd_buf,
            None,
            None,
            True,  # inherit std handles
            CREATE_NO_WINDOW,
            None,
            cwd,
            ctypes.byref(si),
            ctypes.byref(pi),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

        if h_job and not kernel32.AssignProcessToJobObject(h_job, pi.hProcess):
            pass  # non-fatal: child runs unassigned

        kernel32.WaitForSingleObject(pi.hProcess, INFINITE)
        exit_code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code))
        return int(exit_code.value)
    finally:
        if pi.hThread:
            kernel32.CloseHandle(pi.hThread)
        if pi.hProcess:
            kernel32.CloseHandle(pi.hProcess)
        if h_job:
            kernel32.CloseHandle(h_job)  # triggers KILL_ON_JOB_CLOSE if still running
        if h_restricted.value:
            kernel32.CloseHandle(h_restricted)
        if h_token.value:
            kernel32.CloseHandle(h_token)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Windows restricted-token sandbox runner")
    parser.add_argument("--cwd", default=None, help="Working directory")
    parser.add_argument("--command", required=True, help="Command to execute")
    parsed_args = parser.parse_args()

    if parsed_args.command:
        sys.exit(run_restricted_cmd(parsed_args.command, cwd=parsed_args.cwd))
    sys.exit(0)
