/* win.c - Windows implementations of the POSIX functions declared in compat_win.h.
 * Only compiled into the Windows runtime.
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */
#ifdef _WIN32
#include "qbrt_int.h"
#include <ctype.h>

/* ---- threads ---------------------------------------------------------- */
typedef struct { void *(*fn)(void *); void *arg; } thread_start;

static unsigned __stdcall thread_tramp(void *p)
{
    thread_start s = *(thread_start *)p;
    free(p);
    s.fn(s.arg);
    return 0;
}

int pthread_create(pthread_t *t, void *attr, void *(*fn)(void *), void *arg)
{
    (void)attr;
    thread_start *s = malloc(sizeof *s);
    if (!s) return -1;
    s->fn = fn; s->arg = arg;
    uintptr_t h = _beginthreadex(NULL, 0, thread_tramp, s, 0, NULL);
    if (!h) { free(s); return -1; }
    *t = (HANDLE)h;
    return 0;
}

int pthread_join(pthread_t t, void **ret)
{
    if (ret) *ret = NULL;
    WaitForSingleObject(t, INFINITE);
    CloseHandle(t);
    return 0;
}

int pthread_cond_timedwait(pthread_cond_t *c, pthread_mutex_t *m, const struct timespec *abstime)
{
    struct timespec now;
    clock_gettime(CLOCK_REALTIME, &now);
    double ms = (abstime->tv_sec - now.tv_sec) * 1000.0 + (abstime->tv_nsec - now.tv_nsec) / 1e6;
    if (ms < 0) ms = 0;
    return SleepConditionVariableSRW(c, m, (unsigned long)ms, 0) ? 0 : 110 /* ETIMEDOUT */;
}

/* ---- time ------------------------------------------------------------- */
int clock_gettime(int clk, struct timespec *ts)
{
    if (clk == CLOCK_MONOTONIC) {
        static LARGE_INTEGER freq;
        LARGE_INTEGER c;
        if (!freq.QuadPart) QueryPerformanceFrequency(&freq);
        QueryPerformanceCounter(&c);
        ts->tv_sec = (time_t)(c.QuadPart / freq.QuadPart);
        ts->tv_nsec = (long)((c.QuadPart % freq.QuadPart) * 1000000000LL / freq.QuadPart);
        return 0;
    }
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    unsigned long long t = ((unsigned long long)ft.dwHighDateTime << 32) | ft.dwLowDateTime;
    t -= 116444736000000000ULL;                 /* 1601 -> 1970, in 100 ns units */
    ts->tv_sec = (time_t)(t / 10000000ULL);
    ts->tv_nsec = (long)(t % 10000000ULL) * 100;
    return 0;
}

int gettimeofday(struct timeval *tv, void *tz)
{
    (void)tz;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    tv->tv_sec = (long)ts.tv_sec;
    tv->tv_usec = ts.tv_nsec / 1000;
    return 0;
}

int nanosleep(const struct timespec *req, struct timespec *rem)
{
    if (rem) { rem->tv_sec = 0; rem->tv_nsec = 0; }
    double ms = req->tv_sec * 1000.0 + req->tv_nsec / 1e6;
    Sleep(ms < 1 && ms > 0 ? 1 : (DWORD)ms);
    return 0;
}

__declspec(dllimport) int __cdecl _localtime64_s(struct tm *, const long long *);
struct tm *localtime_r(const time_t *t, struct tm *out)
{
    long long v = (long long)*t;
    return _localtime64_s(out, &v) == 0 ? out : NULL;
}

/* ---- environment ------------------------------------------------------ */
int setenv(const char *name, const char *value, int overwrite)
{
    if (!overwrite && getenv(name)) return 0;
    return _putenv_s(name, value) == 0 ? 0 : -1;
}

int unsetenv(const char *name)
{
    return _putenv_s(name, "") == 0 ? 0 : -1;
}

/* ---- directories ------------------------------------------------------ */
struct qbw_dir {
    HANDLE h;
    WIN32_FIND_DATAA fd;
    int first;
    struct dirent ent;
};

DIR *opendir(const char *path)
{
    char pat[MAX_PATH + 4];
    size_t n = strlen(path);
    if (n == 0) { path = "."; n = 1; }
    snprintf(pat, sizeof pat, "%s%s*", path, (path[n - 1] == '\\' || path[n - 1] == '/' || path[n - 1] == ':') ? "" : "\\");
    DIR *d = calloc(1, sizeof *d);
    if (!d) return NULL;
    d->h = FindFirstFileA(pat, &d->fd);
    if (d->h == INVALID_HANDLE_VALUE) { free(d); errno = ENOENT; return NULL; }
    d->first = 1;
    return d;
}

struct dirent *readdir(DIR *d)
{
    if (!d) return NULL;
    if (d->first) d->first = 0;
    else if (!FindNextFileA(d->h, &d->fd)) return NULL;
    snprintf(d->ent.d_name, sizeof d->ent.d_name, "%s", d->fd.cFileName);
    return &d->ent;
}

int closedir(DIR *d)
{
    if (!d) return -1;
    FindClose(d->h);
    free(d);
    return 0;
}

/* shell-style wildcard match: * ? [set] */
int fnmatch(const char *p, const char *s, int flags)
{
    int fold = flags & FNM_CASEFOLD;
#define FOLD(c) (fold ? tolower((unsigned char)(c)) : (unsigned char)(c))
    const char *star = NULL, *ss = NULL;
    while (*s) {
        if (*p == '*') { star = p++; ss = s; continue; }
        if (*p == '?') { p++; s++; continue; }
        if (*p == '[') {
            const char *q = p + 1; int neg = 0, ok = 0;
            if (*q == '!' || *q == '^') { neg = 1; q++; }
            while (*q && *q != ']') {
                if (q[1] == '-' && q[2] && q[2] != ']') { if (FOLD(*s) >= FOLD(q[0]) && FOLD(*s) <= FOLD(q[2])) ok = 1; q += 3; }
                else { if (FOLD(*s) == FOLD(*q)) ok = 1; q++; }
            }
            if (*q == ']' && ok != neg) { p = q + 1; s++; continue; }
        } else if (*p && FOLD(*p) == FOLD(*s)) { p++; s++; continue; }
        if (star) { p = star + 1; s = ++ss; continue; }
        return 1;
    }
    while (*p == '*') p++;
    return *p ? 1 : 0;
#undef FOLD
}

/* ---- maths ------------------------------------------------------------ */
double nearbyint(double x)
{
    /* round half to even (the default rounding mode) */
    double f = floor(x), d = x - f;
    if (d > 0.5) return f + 1;
    if (d < 0.5) return f;
    return fmod(f, 2.0) == 0 ? f : f + 1;
}

/* ---- stdin without blocking (redirected input) ------------------------- */
int qbw_stdin_available(void)
{
    HANDLE h = GetStdHandle(STD_INPUT_HANDLE);
    DWORD type = GetFileType(h);
    if (type == FILE_TYPE_PIPE) {
        DWORD n = 0;
        if (!PeekNamedPipe(h, NULL, 0, NULL, &n, NULL)) return -1;   /* closed */
        return n > 0;
    }
    if (type == FILE_TYPE_DISK) return 1;
    return 0;
}
#endif
