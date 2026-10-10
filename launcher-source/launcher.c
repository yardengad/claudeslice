/* Video Slicer launcher for Windows.
 *
 * A tiny native GUI-subsystem exe (no console window) that finds a REAL
 * Python install and starts the Tkinter GUI (app\video_slicer_gui.py).
 *
 * Why this isn't just "run pythonw.exe": Windows 10/11 ship fake
 * python.exe / pythonw.exe stubs on PATH by default (App Execution
 * Aliases) even when Python was never installed. Those stubs make
 * CreateProcessW report success, so a naive launcher silently does
 * nothing and the user never sees an error. This launcher instead:
 *
 *   1. Looks for the real Python Launcher (py.exe / pyw.exe in the
 *      Windows directory) - installed by the official python.org
 *      installer and NOT shadowed by the Store stub.
 *   2. Falls back to scanning the well-known real install folders for
 *      pythonw.exe directly.
 *   3. As a last resort, resolves "pythonw.exe" via PATH but rejects it
 *      if it resolves into \WindowsApps\ (the stub's location).
 *   4. If nothing real is found, shows a clear message box instead of
 *      failing silently.
 *   5. Always redirects the launched Python process's stdout/stderr to
 *      a log file next to this exe, so if the GUI script itself crashes
 *      on startup (e.g. a missing module), there is something to open
 *      and read instead of silence.
 */
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

static BOOL FileExistsW(LPCWSTR path) {
    DWORD attrs = GetFileAttributesW(path);
    return (attrs != INVALID_FILE_ATTRIBUTES) && !(attrs & FILE_ATTRIBUTE_DIRECTORY);
}

/* Tries the official Python Launcher (pyw.exe) in the Windows directory.
 * This is installed by the python.org installer (default option) and is
 * a reliable real-Python signal, unlike python.exe/pythonw.exe on PATH. */
static BOOL FindPyLauncher(LPWSTR outPath, DWORD outCap) {
    wchar_t winDir[MAX_PATH];
    UINT n = GetWindowsDirectoryW(winDir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return FALSE;

    wchar_t candidate[MAX_PATH];
    wsprintfW(candidate, L"%s\\pyw.exe", winDir);
    if (FileExistsW(candidate)) {
        lstrcpynW(outPath, candidate, outCap);
        return TRUE;
    }
    return FALSE;
}

/* Scans one parent directory for subfolders matching "Python3*" and
 * returns the first one containing a real pythonw.exe. */
static BOOL ScanForPythonInDir(LPCWSTR parentDir, LPWSTR outPath, DWORD outCap) {
    wchar_t pattern[MAX_PATH];
    wsprintfW(pattern, L"%s\\Python3*", parentDir);

    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return FALSE;

    BOOL found = FALSE;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            wchar_t candidate[MAX_PATH];
            wsprintfW(candidate, L"%s\\%s\\pythonw.exe", parentDir, fd.cFileName);
            if (FileExistsW(candidate)) {
                lstrcpynW(outPath, candidate, outCap);
                found = TRUE;
                break;
            }
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return found;
}

/* Last resort: resolve "pythonw.exe" via PATH, but reject it if it is
 * the Microsoft Store's fake stub (lives under \WindowsApps\). */
static BOOL FindRealPythonwOnPath(LPWSTR outPath, DWORD outCap) {
    wchar_t resolved[MAX_PATH];
    DWORD len = SearchPathW(NULL, L"pythonw.exe", NULL, MAX_PATH, resolved, NULL);
    if (len == 0 || len >= MAX_PATH) return FALSE;
    if (wcsstr(resolved, L"WindowsApps") != NULL) return FALSE;  /* fake stub */
    lstrcpynW(outPath, resolved, outCap);
    return TRUE;
}

/* Finds a real, working Python. Tries, in order: the py launcher, the
 * usual per-user and all-users install folders, then a PATH lookup that
 * explicitly excludes the Store stub. */
static BOOL FindRealPython(LPWSTR outPath, DWORD outCap, BOOL *isPyLauncher) {
    *isPyLauncher = FALSE;

    if (FindPyLauncher(outPath, outCap)) {
        *isPyLauncher = TRUE;
        return TRUE;
    }

    wchar_t localAppData[MAX_PATH];
    if (GetEnvironmentVariableW(L"LOCALAPPDATA", localAppData, MAX_PATH)) {
        wchar_t progDir[MAX_PATH];
        wsprintfW(progDir, L"%s\\Programs\\Python", localAppData);
        if (ScanForPythonInDir(progDir, outPath, outCap)) return TRUE;
    }

    wchar_t programFiles[MAX_PATH];
    if (GetEnvironmentVariableW(L"ProgramFiles", programFiles, MAX_PATH)) {
        if (ScanForPythonInDir(programFiles, outPath, outCap)) return TRUE;
    }

    wchar_t programFilesX86[MAX_PATH];
    if (GetEnvironmentVariableW(L"ProgramFiles(x86)", programFilesX86, MAX_PATH)) {
        if (ScanForPythonInDir(programFilesX86, outPath, outCap)) return TRUE;
    }

    if (FindRealPythonwOnPath(outPath, outCap)) return TRUE;

    return FALSE;
}

int APIENTRY wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                       LPWSTR lpCmdLine, int nCmdShow) {
    wchar_t exeDir[MAX_PATH];
    GetModuleFileNameW(NULL, exeDir, MAX_PATH);
    wchar_t *lastSlash = wcsrchr(exeDir, L'\\');
    if (lastSlash) *lastSlash = L'\0';

    wchar_t scriptPath[MAX_PATH];
    wsprintfW(scriptPath, L"%s\\app\\video_slicer_gui.py", exeDir);

    wchar_t pythonPath[MAX_PATH];
    BOOL isPyLauncher = FALSE;
    if (!FindRealPython(pythonPath, MAX_PATH, &isPyLauncher)) {
        int choice = MessageBoxW(NULL,
            L"Video Slicer needs Python 3, which was not found on this PC.\n\n"
            L"Click OK to open the Python download page. During setup, make sure "
            L"to check \"Add python.exe to PATH\" AND leave \"tcl/tk and IDLE\" "
            L"checked (it's on by default). After installing, reopen Video Slicer.",
            L"Video Slicer",
            MB_OKCANCEL | MB_ICONINFORMATION);
        if (choice == IDOK) {
            ShellExecuteW(NULL, L"open", L"https://www.python.org/downloads/windows/",
                          NULL, NULL, SW_SHOWNORMAL);
        }
        return 0;
    }

    /* Build the command line: either "pyw.exe <script>" or
     * "<full pythonw path>" <script>", both quoted safely. */
    wchar_t cmdLine[MAX_PATH * 2];
    if (isPyLauncher) {
        wsprintfW(cmdLine, L"\"%s\" \"%s\"", pythonPath, scriptPath);
    } else {
        wsprintfW(cmdLine, L"\"%s\" \"%s\"", pythonPath, scriptPath);
    }

    /* Redirect the child's stdout/stderr to a log file next to the exe,
     * so a Python-side crash on startup leaves something readable
     * instead of total silence. */
    wchar_t logPath[MAX_PATH];
    wsprintfW(logPath, L"%s\\VideoSlicer_debug_log.txt", exeDir);

    SECURITY_ATTRIBUTES sa;
    ZeroMemory(&sa, sizeof(sa));
    sa.nLength = sizeof(sa);
    sa.bInheritHandle = TRUE;

    HANDLE hLog = CreateFileW(logPath, GENERIC_WRITE, FILE_SHARE_READ, &sa,
                               CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    if (hLog != INVALID_HANDLE_VALUE) {
        si.dwFlags |= STARTF_USESTDHANDLES;
        si.hStdOutput = hLog;
        si.hStdError = hLog;
    }

    BOOL ok = CreateProcessW(
        NULL,
        cmdLine,
        NULL, NULL,
        hLog != INVALID_HANDLE_VALUE ? TRUE : FALSE,  /* inherit handles only if we have a log */
        CREATE_NO_WINDOW,
        NULL,
        exeDir,
        &si, &pi
    );

    if (hLog != INVALID_HANDLE_VALUE) CloseHandle(hLog);

    if (ok) {
        /* Give it a moment, then check whether it exited immediately
         * with an error (a crash on import, say) - if so, surface that
         * instead of leaving the user staring at nothing. */
        DWORD waitResult = WaitForSingleObject(pi.hProcess, 2000);
        if (waitResult == WAIT_OBJECT_0) {
            DWORD exitCode = 0;
            GetExitCodeProcess(pi.hProcess, &exitCode);
            if (exitCode != 0) {
                MessageBoxW(NULL,
                    L"Video Slicer closed immediately with an error.\n\n"
                    L"A log file was written next to Video Slicer.exe called "
                    L"\"VideoSlicer_debug_log.txt\" - please open it to see what "
                    L"went wrong (this usually means a piece of Python is missing, "
                    L"such as the tcl/tk component).",
                    L"Video Slicer", MB_OK | MB_ICONWARNING);
            }
        }
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    } else {
        MessageBoxW(NULL,
            L"Video Slicer found Python but could not start it. "
            L"Please reinstall Python from python.org and try again.",
            L"Video Slicer", MB_OK | MB_ICONERROR);
    }

    return 0;
}
