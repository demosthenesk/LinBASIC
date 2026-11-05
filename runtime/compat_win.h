/* compat_win.h - the small part of POSIX the runtime needs, on top of Win32 / msvcrt.
 * Used when the runtime is built for Windows (x86_64-win32-tcc).
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */
#ifndef QB_COMPAT_WIN_H
#define QB_COMPAT_WIN_H
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <io.h>
#include <direct.h>
#include <process.h>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <errno.h>
#include <time.h>

/* ---- threads: SRW locks and condition variables (Vista and later) ---- */
typedef struct { void *p; } qbw_srw;
typedef struct { void *p; } qbw_cv;
__declspec(dllimport) void __stdcall AcquireSRWLockExclusive(qbw_srw *);
__declspec(dllimport) void __stdcall ReleaseSRWLockExclusive(qbw_srw *);
__declspec(dllimport) int __stdcall SleepConditionVariableSRW(qbw_cv *, qbw_srw *, unsigned long, unsigned long);
__declspec(dllimport) void __stdcall WakeConditionVariable(qbw_cv *);
__declspec(dllimport) void __stdcall WakeAllConditionVariable(qbw_cv *);

typedef qbw_srw pthread_mutex_t;
typedef qbw_cv pthread_cond_t;
typedef HANDLE pthread_t;
#define PTHREAD_MUTEX_INITIALIZER { 0 }
#define PTHREAD_COND_INITIALIZER { 0 }
static __inline int pthread_mutex_lock(pthread_mutex_t *m) { AcquireSRWLockExclusive(m); return 0; }
static __inline int pthread_mutex_unlock(pthread_mutex_t *m) { ReleaseSRWLockExclusive(m); return 0; }
static __inline int pthread_cond_signal(pthread_cond_t *c) { WakeConditionVariable(c); return 0; }
static __inline int pthread_cond_broadcast(pthread_cond_t *c) { WakeAllConditionVariable(c); return 0; }

#ifndef _TIMESPEC_DEFINED
#define _TIMESPEC_DEFINED
struct timespec { time_t tv_sec; long tv_nsec; };
#endif
struct qbw_timeval { long tv_sec; long tv_usec; };
#define timeval qbw_timeval

int pthread_cond_timedwait(pthread_cond_t *c, pthread_mutex_t *m, const struct timespec *abstime);
int pthread_create(pthread_t *t, void *attr, void *(*fn)(void *), void *arg);
int pthread_join(pthread_t t, void **ret);

/* ---- time ---------------------------------------------------------------- */
#define CLOCK_REALTIME 0
#define CLOCK_MONOTONIC 1
int clock_gettime(int clk, struct timespec *ts);
int nanosleep(const struct timespec *req, struct timespec *rem);
int gettimeofday(struct timeval *tv, void *tz);

struct tm *localtime_r(const time_t *t, struct tm *out);

/* ---- strings, environment, files ----------------------------------------- */
#define strcasecmp _stricmp
#define strncasecmp _strnicmp
#define strtok_r strtok_s
int setenv(const char *name, const char *value, int overwrite);
int unsetenv(const char *name);
#define isatty _isatty
#define unlink _unlink
#define getpid _getpid
#define fileno _fileno
#define getcwd _getcwd
#define chdir _chdir
#define rmdir _rmdir
#define mkdir(p, m) _mkdir(p)
#ifndef S_ISDIR
#define S_ISDIR(m) (((m) & S_IFMT) == S_IFDIR)
#endif
#ifndef EXDEV
#define EXDEV 18
#endif

/* directories (FindFirstFile) and shell-style matching */
struct dirent { char d_name[MAX_PATH]; };
typedef struct qbw_dir DIR;
DIR *opendir(const char *path);
struct dirent *readdir(DIR *d);
int closedir(DIR *d);
#define FNM_CASEFOLD 16
int fnmatch(const char *pattern, const char *name, int flags);

/* C99 maths missing from msvcrt.dll (round and trunc come inline from tcc's math.h) */
double nearbyint(double);

/* console / window helpers shared by display.c */
int qbw_stdin_available(void);
#endif
