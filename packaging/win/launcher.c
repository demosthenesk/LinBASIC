/* launcher.c - LinBASIC.exe (the IDE) and lbc.exe (the compiler) of the Windows portable edition.
 * Both start the bundled Python (python\) with LINBASIC_HOME set to the program folder.
 *   LinBASIC.exe  ->  python\pythonw.exe -m linbasic [files...]      (built with -DGUI)
 *   lbc.exe       ->  python\python.exe compiler\lbc.py [options] FILE.BAS
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

static const wchar_t *skip_argv0(const wchar_t *c)
{
    if (*c == L'"') {
        c++;
        while (*c && *c != L'"') c++;
        if (*c) c++;
    } else {
        while (*c && *c != L' ' && *c != L'\t') c++;
    }
    while (*c == L' ' || *c == L'\t') c++;
    return c;
}

static void fail(const wchar_t *msg)
{
#ifdef GUI
    MessageBoxW(NULL, msg, L"LinBASIC", MB_OK | MB_ICONERROR);
#else
    DWORD n;
    HANDLE h = GetStdHandle(STD_ERROR_HANDLE);
    WriteConsoleW(h, msg, (DWORD)wcslen(msg), &n, NULL);
    WriteConsoleW(h, L"\r\n", 2, &n, NULL);
#endif
}

#ifdef GUI
int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, LPWSTR cmdline, int show)
#else
int wmain(void)
#endif
{
    static wchar_t home[MAX_PATH], py[MAX_PATH + 32], cmd[32768];
    DWORD n = GetModuleFileNameW(NULL, home, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) { fail(L"Cannot find the program folder."); return 1; }
    wchar_t *slash = wcsrchr(home, L'\\');
    if (slash) *slash = 0;
    SetEnvironmentVariableW(L"LINBASIC_HOME", home);
    SetEnvironmentVariableW(L"PYTHONHOME", NULL);
    SetEnvironmentVariableW(L"PYTHONPATH", NULL);
    SetEnvironmentVariableW(L"QT_PLUGIN_PATH", NULL);
    const wchar_t *args = skip_argv0(GetCommandLineW());
#ifdef GUI
    _snwprintf(py, MAX_PATH + 32, L"%s\\python\\pythonw.exe", home);
    _snwprintf(cmd, 32768, L"\"%s\" -m linbasic %s", py, args);
#else
    _snwprintf(py, MAX_PATH + 32, L"%s\\python\\python.exe", home);
    _snwprintf(cmd, 32768, L"\"%s\" \"%s\\compiler\\lbc.py\" %s", py, home, args);
#endif
    cmd[32767] = 0;
    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES) {
        fail(L"The python folder of LinBASIC is missing. Extract the whole zip file and start LinBASIC from there.");
        return 1;
    }
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    if (!CreateProcessW(py, cmd, NULL, NULL, TRUE, 0, NULL, NULL, &si, &pi)) {
        wchar_t msg[600];
        _snwprintf(msg, 600, L"Could not start %s (error %lu).", py, GetLastError());
        msg[599] = 0;
        fail(msg);
        return 1;
    }
    CloseHandle(pi.hThread);
#ifdef GUI
    CloseHandle(pi.hProcess);
    return 0;
#else
    SetConsoleCtrlHandler(NULL, TRUE);          /* Ctrl+C goes to lbc, not to this launcher */
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    return (int)code;
#endif
}
