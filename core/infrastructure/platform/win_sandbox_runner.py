"""Windows Safer Token sandbox runner for executing child processes with restricted tokens.

Uses standard Win32 Safer API (Advapi32.dll) to execute commands under a
SAFER_LEVEL_NORMALUSER restricted token with stripped administrative privileges.
"""
from __future__ import annotations

import sys


def run_safer_cmd(cmd: str, cwd: str | None = None) -> int:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    SAFER_SCOPE_USER = 1
    SAFER_LEVEL_NORMALUSER = 0x20000
    SAFER_LEVEL_OPEN = 1
    SAFER_LEVEL_HANDLE = wintypes.HANDLE

    advapi32.SaferCreateLevel.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(SAFER_LEVEL_HANDLE),
        ctypes.c_void_p,
    ]
    advapi32.SaferCreateLevel.restype = wintypes.BOOL

    advapi32.SaferComputeTokenFromLevel.argtypes = [
        SAFER_LEVEL_HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    advapi32.SaferComputeTokenFromLevel.restype = wintypes.BOOL

    advapi32.SaferCloseLevel.argtypes = [SAFER_LEVEL_HANDLE]
    advapi32.SaferCloseLevel.restype = wintypes.BOOL

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL

    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE

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

    advapi32.CreateProcessWithTokenW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    advapi32.CreateProcessWithTokenW.restype = wintypes.BOOL

    h_level = SAFER_LEVEL_HANDLE()
    if not advapi32.SaferCreateLevel(
        SAFER_SCOPE_USER, SAFER_LEVEL_NORMALUSER, SAFER_LEVEL_OPEN, ctypes.byref(h_level), None
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    h_proc = kernel32.GetCurrentProcess()
    h_token = wintypes.HANDLE()
    token_access = 0x000F0000 | 0x001F | 0x0002 | 0x0004 | 0x0008 | 0x0010 | 0x0020 | 0x0040 | 0x0080 | 0x0100
    if not advapi32.OpenProcessToken(h_proc, token_access, ctypes.byref(h_token)):
        advapi32.SaferCloseLevel(h_level)
        raise ctypes.WinError(ctypes.get_last_error())

    h_safer_token = wintypes.HANDLE()
    if not advapi32.SaferComputeTokenFromLevel(h_level, h_token, ctypes.byref(h_safer_token), 0, None):
        err = ctypes.get_last_error()
        advapi32.SaferCloseLevel(h_level)
        kernel32.CloseHandle(h_token)
        raise ctypes.WinError(err)

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.hStdInput = kernel32.GetStdHandle(-10)
    si.hStdOutput = kernel32.GetStdHandle(-11)
    si.hStdError = kernel32.GetStdHandle(-12)
    si.dwFlags |= 0x00000100  # STARTF_USESTDHANDLES

    pi = PROCESS_INFORMATION()

    cmd_buf = ctypes.create_unicode_buffer(cmd)
    LOGON_WITH_PROFILE = 1
    CREATE_NO_WINDOW = 0x08000000

    ok = advapi32.CreateProcessWithTokenW(
        h_safer_token,
        LOGON_WITH_PROFILE,
        None,
        cmd_buf,
        CREATE_NO_WINDOW,
        None,
        cwd,
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    if not ok:
        err = ctypes.get_last_error()
        advapi32.SaferCloseLevel(h_level)
        kernel32.CloseHandle(h_safer_token)
        kernel32.CloseHandle(h_token)
        raise ctypes.WinError(err)

    kernel32.WaitForSingleObject(pi.hProcess, 0xFFFFFFFF)
    exit_code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code))

    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    advapi32.SaferCloseLevel(h_level)
    kernel32.CloseHandle(h_safer_token)
    kernel32.CloseHandle(h_token)
    return int(exit_code.value)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        sys.exit(run_safer_cmd(command))
    sys.exit(0)
