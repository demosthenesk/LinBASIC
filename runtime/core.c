/* core.c - strings, arrays, numbers, errors, DATA, program control.
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */
#include "qbrt_int.h"
#include <stdarg.h>
#include <time.h>
#include <ctype.h>
#include <errno.h>
#ifndef _WIN32
#include <unistd.h>
#include <sys/time.h>
#include <sys/wait.h>
#endif

char qb_module_name[64] = "MAIN";
int qb_rt_flags;
static int g_argc;
static char **g_argv;
volatile qb_i32 qb_errpend;
qb_i32 qb_err, qb_erl, qb_errline, qb_handler_on, qb_in_handler;
qb_i32 qb_curline;
volatile qb_i32 qb_evflag;
int qb_break_flag;

/* ------------------------------------------------------------------ */
/* temporary string stack                                              */
static char **tmp_stack;
static qb_i32 tmp_n, tmp_cap;

static void tmp_push(char *p)
{
    if (tmp_n == tmp_cap) {
        tmp_cap = tmp_cap ? tmp_cap * 2 : 256;
        tmp_stack = realloc(tmp_stack, tmp_cap * sizeof(char *));
    }
    tmp_stack[tmp_n++] = p;
}

qb_i32 qb_mark(void) { return tmp_n; }

void qb_release(qb_i32 m)
{
    while (tmp_n > m) free(tmp_stack[--tmp_n]);
}

static void oom(void) { fprintf(stderr, "Out of memory\n"); exit(7); }

qbs qb_stmp(qb_i32 len)
{
    qbs r;
    if (len < 0) len = 0;
    r.p = malloc(len + 1);
    if (!r.p) oom();
    r.p[len] = 0;
    r.len = len;
    r.flags = 0;
    tmp_push(r.p);
    return r;
}

qbs qb_slit(const char *s, qb_i32 len) { qbs r; r.p = (char *)s; r.len = len; r.flags = 0; return r; }

qbs qb_scopy(qbs s)
{
    qbs r = qb_stmp(s.len);
    if (s.len) memcpy(r.p, s.p, s.len);
    return r;
}

char *qb_cstr(qbs s) { qbs r = qb_scopy(s); return r.p; }

void qb_sset(qbs *dst, qbs src)
{
    char *np = NULL;
    if (src.len > 0) {
        np = malloc(src.len + 1);
        if (!np) oom();
        memcpy(np, src.p, src.len);
        np[src.len] = 0;
    }
    if ((dst->flags & 1) && dst->p) free(dst->p);
    dst->p = np;
    dst->len = src.len;
    dst->flags = np ? 1 : 0;
}

void qb_sfree(qbs *v)
{
    if ((v->flags & 1) && v->p) free(v->p);
    v->p = NULL; v->len = 0; v->flags = 0;
}

qbs qb_sadd(qbs a, qbs b)
{
    qbs r = qb_stmp(a.len + b.len);
    if (a.len) memcpy(r.p, a.p, a.len);
    if (b.len) memcpy(r.p + a.len, b.p, b.len);
    return r;
}

qb_i32 qb_scmp(qbs a, qbs b)
{
    int n = a.len < b.len ? a.len : b.len;
    int c = n ? memcmp(a.p, b.p, n) : 0;
    if (c) return c < 0 ? -1 : 1;
    return a.len < b.len ? -1 : a.len > b.len ? 1 : 0;
}

qbs qb_fsget(const char *buf, qb_i32 n) { return qb_slit(buf, n); }

void qb_fsset(char *buf, qb_i32 n, qbs src)
{
    int k = src.len < n ? src.len : n;
    if (k) memmove(buf, src.p, k);
    if (n > k) memset(buf + k, ' ', n - k);
}

void qb_fsinit(char *buf, qb_i32 n) { memset(buf, 0, n); }

qbs qb_left(qbs s, qb_i32 n)
{
    if (n < 0) { qb_error(5); return qb_slit("", 0); }
    if (n > s.len) n = s.len;
    qbs r = qb_stmp(n); memcpy(r.p, s.p, n); return r;
}

qbs qb_right(qbs s, qb_i32 n)
{
    if (n < 0) { qb_error(5); return qb_slit("", 0); }
    if (n > s.len) n = s.len;
    qbs r = qb_stmp(n); memcpy(r.p, s.p + s.len - n, n); return r;
}

qbs qb_mid(qbs s, qb_i32 start, qb_i32 n)
{
    if (start < 1 || (n != QB_NA && n < 0)) { qb_error(5); return qb_slit("", 0); }
    if (start > s.len) return qb_slit("", 0);
    int avail = s.len - start + 1;
    if (n == QB_NA || n > avail) n = avail;
    qbs r = qb_stmp(n); memcpy(r.p, s.p + start - 1, n); return r;
}

void qb_mid_stmt(qbs *dst, qb_i32 start, qb_i32 n, qbs src)
{
    if (start < 1 || start > dst->len) { qb_error(5); return; }
    int avail = dst->len - start + 1;
    if (n == QB_NA || n > src.len) n = src.len;
    if (n > avail) n = avail;
    if (n <= 0) return;
    if (dst->flags & 1 || dst->flags & 2) { memmove(dst->p + start - 1, src.p, n); return; }
    qbs c = qb_scopy(*dst);
    memmove(c.p + start - 1, src.p, n);
    qb_sset(dst, c);
}

void qb_mid_stmt_fs(char *buf, qb_i32 blen, qb_i32 start, qb_i32 n, qbs src)
{
    if (start < 1 || start > blen) { qb_error(5); return; }
    int avail = blen - start + 1;
    if (n == QB_NA || n > src.len) n = src.len;
    if (n > avail) n = avail;
    if (n > 0) memmove(buf + start - 1, src.p, n);
}

qbs qb_ltrim(qbs s) { int i = 0; while (i < s.len && s.p[i] == ' ') i++; return qb_mid(s, i + 1, QB_NA); }
qbs qb_rtrim(qbs s) { int n = s.len; while (n > 0 && s.p[n - 1] == ' ') n--; return qb_left(s, n); }

qbs qb_ucase(qbs s) { qbs r = qb_scopy(s); for (int i = 0; i < r.len; i++) if (r.p[i] >= 'a' && r.p[i] <= 'z') r.p[i] -= 32; return r; }
qbs qb_lcase(qbs s) { qbs r = qb_scopy(s); for (int i = 0; i < r.len; i++) if (r.p[i] >= 'A' && r.p[i] <= 'Z') r.p[i] += 32; return r; }

qbs qb_chr(qb_i32 c)
{
    if (c < 0 || c > 255) { qb_error(5); c = 0; }
    qbs r = qb_stmp(1); r.p[0] = (char)c; return r;
}

qb_i32 qb_asc(qbs s)
{
    if (s.len == 0) { qb_error(5); return 0; }
    return (unsigned char)s.p[0];
}

qb_i32 qb_instr(qb_i32 start, qbs a, qbs b)
{
    if (start == QB_NA) start = 1;
    if (start < 1) { qb_error(5); return 0; }
    if (start > a.len) return 0;
    if (b.len == 0) return start;
    for (int i = start - 1; i + b.len <= a.len; i++)
        if (memcmp(a.p + i, b.p, b.len) == 0) return i + 1;
    return 0;
}

qbs qb_space(qb_i32 n) { if (n < 0) { qb_error(5); n = 0; } qbs r = qb_stmp(n); memset(r.p, ' ', n); return r; }
qbs qb_string_n(qb_i32 n, qb_i32 c)
{
    if (n < 0 || c < 0 || c > 255) { qb_error(5); return qb_slit("", 0); }
    qbs r = qb_stmp(n); memset(r.p, c, n); return r;
}
qbs qb_string_s(qb_i32 n, qbs c)
{
    if (c.len == 0) { qb_error(5); return qb_slit("", 0); }
    return qb_string_n(n, (unsigned char)c.p[0]);
}

qbs qb_str_i(qb_i32 v)
{
    char b[24]; int n = snprintf(b, sizeof b, v < 0 ? "%d" : " %d", v);
    qbs r = qb_stmp(n); memcpy(r.p, b, n); return r;
}
qbs qb_str_f(float v)
{
    char b[48]; qb_fmt_single(v, b + 1); b[0] = ' ';
    char *s = b[1] == '-' ? b + 1 : b; int n = strlen(s);
    qbs r = qb_stmp(n); memcpy(r.p, s, n); return r;
}
qbs qb_str_d(double v)
{
    char b[48]; qb_fmt_double(v, b + 1); b[0] = ' ';
    char *s = b[1] == '-' ? b + 1 : b; int n = strlen(s);
    qbs r = qb_stmp(n); memcpy(r.p, s, n); return r;
}

double qb_val(qbs s)
{
    /* VAL ignores blanks, tabs and line feeds anywhere in the number */
    char buf[128]; int n = 0;
    int i = 0;
    while (i < s.len && (s.p[i] == ' ' || s.p[i] == '\t' || s.p[i] == '\n')) i++;
    if (i + 1 < s.len && s.p[i] == '&') {
        int base = 16; i++;
        if (s.p[i] == 'H' || s.p[i] == 'h') { base = 16; i++; }
        else if (s.p[i] == 'O' || s.p[i] == 'o') { base = 8; i++; }
        else base = 8;
        long long v = 0;
        for (; i < s.len; i++) {
            int c = toupper((unsigned char)s.p[i]), d;
            if (c == ' ') continue;
            if (c >= '0' && c <= '9') d = c - '0'; else if (c >= 'A' && c <= 'F') d = c - 'A' + 10; else break;
            if (d >= base) break;
            v = v * base + d;
        }
        if (v > 0xFFFFFFFFLL) v &= 0xFFFFFFFFLL;
        if (v <= 0xFFFF && v > 0x7FFF) v -= 0x10000;
        else if (v > 0x7FFFFFFF) v -= 0x100000000LL;
        return (double)v;
    }
    for (; i < s.len && n < 120; i++) {
        char c = s.p[i];
        if (c == ' ' || c == '\t' || c == '\n') continue;
        if (c == 'd' || c == 'D') c = 'E';
        if (isdigit((unsigned char)c) || c == '.' || c == '+' || c == '-' || c == 'e' || c == 'E') {
            if ((c == '+' || c == '-') && n > 0 && buf[n - 1] != 'E' && buf[n - 1] != 'e') break;
            buf[n++] = c;
        } else break;
    }
    buf[n] = 0;
    return strtod(buf, NULL);
}

qbs qb_hex(double d)
{
    qb_i32 v = qb_clng(d);
    char b[16]; uint32_t u = (uint32_t)v;
    if (v >= -32768 && v < 0 && d == (double)(qb_i16)v) u &= 0xFFFF;
    int n = snprintf(b, sizeof b, "%X", u);
    qbs r = qb_stmp(n); memcpy(r.p, b, n); return r;
}
qbs qb_oct(double d)
{
    qb_i32 v = qb_clng(d);
    char b[16]; uint32_t u = (uint32_t)v;
    if (v >= -32768 && v < 0) u &= 0xFFFF;
    int n = snprintf(b, sizeof b, "%o", u);
    qbs r = qb_stmp(n); memcpy(r.p, b, n); return r;
}

qbs qb_mki(qb_i32 v) { qb_i16 x = qb_ci16(v); qbs r = qb_stmp(2); memcpy(r.p, &x, 2); return r; }
qbs qb_mkl(qb_i32 v) { qbs r = qb_stmp(4); memcpy(r.p, &v, 4); return r; }
qbs qb_mks(float v) { qbs r = qb_stmp(4); memcpy(r.p, &v, 4); return r; }
qbs qb_mkd(double v) { qbs r = qb_stmp(8); memcpy(r.p, &v, 8); return r; }
qb_i16 qb_cvi(qbs s) { qb_i16 x = 0; if (s.len < 2) { qb_error(5); return 0; } memcpy(&x, s.p, 2); return x; }
qb_i32 qb_cvl(qbs s) { qb_i32 x = 0; if (s.len < 4) { qb_error(5); return 0; } memcpy(&x, s.p, 4); return x; }
float qb_cvs(qbs s) { float x = 0; if (s.len < 4) { qb_error(5); return 0; } memcpy(&x, s.p, 4); return x; }
double qb_cvd(qbs s) { double x = 0; if (s.len < 8) { qb_error(5); return 0; } memcpy(&x, s.p, 8); return x; }

/* Microsoft Binary Format conversions */
qbs qb_mksmbf(float v)
{
    uint32_t ieee; memcpy(&ieee, &v, 4);
    uint8_t m[4] = {0, 0, 0, 0};
    if (v != 0) {
        int sign = ieee >> 31, exp = ((ieee >> 23) & 0xFF) - 127 + 129;
        uint32_t man = ieee & 0x7FFFFF;
        if (exp > 255) { qb_error(6); exp = 255; }
        if (exp <= 0) exp = 0, man = 0;
        m[3] = exp; m[2] = (sign << 7) | (man >> 16); m[1] = (man >> 8) & 0xFF; m[0] = man & 0xFF;
    }
    qbs r = qb_stmp(4); memcpy(r.p, m, 4); return r;
}
float qb_cvsmbf(qbs s)
{
    if (s.len < 4) { qb_error(5); return 0; }
    uint8_t *m = (uint8_t *)s.p;
    if (m[3] == 0) return 0;
    int sign = m[2] >> 7, exp = m[3] - 129 + 127;
    uint32_t man = ((m[2] & 0x7F) << 16) | (m[1] << 8) | m[0];
    if (exp <= 0) return 0;
    uint32_t ieee = (sign << 31) | ((uint32_t)exp << 23) | man;
    float f; memcpy(&f, &ieee, 4); return f;
}
qbs qb_mkdmbf(double v)
{
    uint64_t ieee; memcpy(&ieee, &v, 8);
    uint8_t m[8] = {0};
    if (v != 0) {
        int sign = ieee >> 63, exp = (int)((ieee >> 52) & 0x7FF) - 1023 + 129;
        uint64_t man = (ieee & 0xFFFFFFFFFFFFFULL) >> 3;   /* 52 -> 49 bits... MBF has 55 */
        man = (ieee & 0xFFFFFFFFFFFFFULL) << 3;            /* 55-bit mantissa */
        if (exp > 255 || exp <= 0) { if (exp > 255) qb_error(6); exp = exp > 255 ? 255 : 0; man = 0; }
        m[7] = exp; m[6] = (sign << 7) | ((man >> 48) & 0x7F);
        for (int i = 5; i >= 0; i--) m[i] = (man >> (8 * i)) & 0xFF;
    }
    qbs r = qb_stmp(8); memcpy(r.p, m, 8); return r;
}
double qb_cvdmbf(qbs s)
{
    if (s.len < 8) { qb_error(5); return 0; }
    uint8_t *m = (uint8_t *)s.p;
    if (m[7] == 0) return 0;
    int sign = m[6] >> 7, exp = m[7] - 129 + 1023;
    uint64_t man = (uint64_t)(m[6] & 0x7F) << 48;
    for (int i = 5; i >= 0; i--) man |= (uint64_t)m[i] << (8 * i);
    uint64_t ieee = ((uint64_t)sign << 63) | ((uint64_t)exp << 52) | (man >> 3);
    double d; memcpy(&d, &ieee, 8); return d;
}

static time_t g_time_offset;
qbs qb_date(void)
{
    time_t t = time(NULL) + g_time_offset; struct tm tm; localtime_r(&t, &tm);
    char b[16]; snprintf(b, sizeof b, "%02d-%02d-%04d", tm.tm_mon + 1, tm.tm_mday, tm.tm_year + 1900);
    qbs r = qb_stmp(10); memcpy(r.p, b, 10); return r;
}
qbs qb_time(void)
{
    time_t t = time(NULL) + g_time_offset; struct tm tm; localtime_r(&t, &tm);
    char b[16]; snprintf(b, sizeof b, "%02d:%02d:%02d", tm.tm_hour, tm.tm_min, tm.tm_sec);
    qbs r = qb_stmp(8); memcpy(r.p, b, 8); return r;
}
void qb_date_set(qbs s) { (void)s; }
void qb_time_set(qbs s) { (void)s; }

qbs qb_command(void)
{
    char buf[4096]; int n = 0;
    for (int i = 1; i < g_argc && n < 4000; i++) {
        if (i > 1) buf[n++] = ' ';
        for (const char *p = g_argv[i]; *p && n < 4000; p++) buf[n++] = toupper((unsigned char)*p);
    }
    qbs r = qb_stmp(n); memcpy(r.p, buf, n); return r;
}

qbs qb_environ_s(qbs name)
{
    char *k = qb_cstr(name);
    char *v = getenv(k);
    if (!v) { for (char *p = k; *p; p++) *p = toupper((unsigned char)*p); v = getenv(k); }
    if (!v) return qb_slit("", 0);
    qbs r = qb_stmp(strlen(v)); memcpy(r.p, v, r.len); return r;
}
extern char **environ;
qbs qb_environ_n(qb_i32 n)
{
    if (n < 1) { qb_error(5); return qb_slit("", 0); }
    for (int i = 0; environ[i]; i++) if (i == n - 1) { qbs r = qb_stmp(strlen(environ[i])); memcpy(r.p, environ[i], r.len); return r; }
    return qb_slit("", 0);
}
void qb_environ_set(qbs s)
{
    char *c = qb_cstr(s); char *eq = strchr(c, '=');
    if (!eq) { qb_error(5); return; }
    *eq = 0; char *k = c, *v = eq + 1;
    while (*k == ' ') k++;
    for (char *p = k; *p; p++) *p = toupper((unsigned char)*p);
    if (*v) setenv(k, v, 1); else unsetenv(k);
}

void qb_lset(qbs *dst, qbs src)
{
    if (dst->len == 0) return;
    int k = src.len < dst->len ? src.len : dst->len;
    char tmp[dst->len];
    memcpy(tmp, src.p, k); memset(tmp + k, ' ', dst->len - k);
    memcpy(dst->p, tmp, dst->len);
}
void qb_rset(qbs *dst, qbs src)
{
    if (dst->len == 0) return;
    int k = src.len < dst->len ? src.len : dst->len;
    char tmp[dst->len];
    memset(tmp, ' ', dst->len - k); memcpy(tmp + dst->len - k, src.p, k);
    memcpy(dst->p, tmp, dst->len);
}
void qb_lset_fs(char *buf, qb_i32 n, qbs src) { qb_fsset(buf, n, src); }
void qb_rset_fs(char *buf, qb_i32 n, qbs src)
{
    int k = src.len < n ? src.len : n;
    char tmp[n]; memset(tmp, ' ', n - k); memcpy(tmp + n - k, src.p, k); memcpy(buf, tmp, n);
}

/* VARPTR$: encode a value so DRAW and PLAY can read it back */
qbs qb_varptrs_num(double v) { qbs r = qb_stmp(9); r.p[0] = 1; memcpy(r.p + 1, &v, 8); return r; }
qbs qb_varptrs_str(qbs s) { qbs r = qb_stmp(5 + s.len); r.p[0] = 2; memcpy(r.p + 1, &s.len, 4); memcpy(r.p + 5, s.p, s.len); return r; }

/* ------------------------------------------------------------------ */
/* arrays (column-major like QB)                                      */
static void arr_setup(qbarr *a, qb_i32 esz, qb_i32 kind, qb_i32 nd, va_list ap)
{
    long long n = 1;
    a->nd = nd; a->esz = esz; a->kind = kind;
    for (int d = 0; d < nd; d++) {
        a->lb[d] = va_arg(ap, qb_i32);
        a->ub[d] = va_arg(ap, qb_i32);
        if (a->ub[d] < a->lb[d]) { qb_error(9); a->ub[d] = a->lb[d]; }
        a->mul[d] = (qb_i32)n;
        n *= (long long)(a->ub[d] - a->lb[d] + 1);
    }
    if (n * esz > 0x7FFFFFFFLL) { qb_error(7); n = 1; }
    a->n = (qb_i32)n;
    a->data = calloc((size_t)n, esz ? esz : 1);
    if (!a->data) oom();
}

void qb_adim(qbarr *a, qb_i32 esz, qb_i32 kind, qb_i32 isdyn, qb_i32 nd, ...)
{
    if (a->nd && a->data) { if (!a->isdyn) { qb_error(10); return; } qb_error(10); return; }
    va_list ap; va_start(ap, nd);
    arr_setup(a, esz, kind, nd, ap);
    va_end(ap);
    a->isdyn = isdyn;
}

void qb_aredim(qbarr *a, qb_i32 esz, qb_i32 kind, qb_i32 nd, ...)
{
    qb_afree(a);
    va_list ap; va_start(ap, nd);
    arr_setup(a, esz, kind, nd, ap);
    va_end(ap);
    a->isdyn = 1;
}

void qb_afree(qbarr *a)
{
    if (a->data && a->kind == 1) {
        qbs *s = (qbs *)a->data;
        for (int i = 0; i < a->n; i++) qb_sfree(&s[i]);
    }
    free(a->data);
    a->data = NULL; a->nd = 0; a->n = 0;
}

void qb_aerase(qbarr *a)
{
    if (!a->data) return;
    if (a->isdyn) { qb_afree(a); return; }
    if (a->kind == 1) { qbs *s = (qbs *)a->data; for (int i = 0; i < a->n; i++) qb_sfree(&s[i]); }
    memset(a->data, 0, (size_t)a->n * a->esz);
}

qb_i32 qb_aoff_err(qbarr *a)
{
    (void)a;
    qb_error(9);
    if (!a->data) { a->data = calloc(1, a->esz > 16 ? a->esz : 16); a->n = 0; }
    return 0;
}

qb_i32 qb_aoff(qbarr *a, qb_i32 nd, ...)
{
    if (a->nd != nd) return qb_aoff_err(a);
    va_list ap; va_start(ap, nd);
    qb_i32 off = 0;
    for (int d = 0; d < nd; d++) {
        qb_i32 i = va_arg(ap, qb_i32);
        if (i < a->lb[d] || i > a->ub[d]) { va_end(ap); return qb_aoff_err(a); }
        off += (i - a->lb[d]) * a->mul[d];
    }
    va_end(ap);
    return off;
}

qb_i32 qb_lbound(qbarr *a, qb_i32 dim)
{
    if (dim == QB_NA) dim = 1;
    if (dim < 1 || dim > a->nd) { qb_error(9); return 0; }
    return a->lb[dim - 1];
}
qb_i32 qb_ubound(qbarr *a, qb_i32 dim)
{
    if (dim == QB_NA) dim = 1;
    if (dim < 1 || dim > a->nd) { qb_error(9); return 0; }
    return a->ub[dim - 1];
}
void qb_acopy(qbarr *dst, qbarr *src)
{
    qb_afree(dst);
    *dst = *src;
    dst->data = malloc((size_t)src->n * src->esz + 1);
    memcpy(dst->data, src->data, (size_t)src->n * src->esz);
    if (src->kind == 1) {
        qbs *s = (qbs *)src->data, *d = (qbs *)dst->data;
        for (int i = 0; i < src->n; i++) { d[i].p = NULL; d[i].flags = 0; d[i].len = 0; qb_sset(&d[i], s[i]); }
    }
}

/* ------------------------------------------------------------------ */
/* numbers                                                             */
static double round_even(double v)
{
    double r = nearbyint(v);   /* default rounding mode: to nearest even */
    return r;
}

qb_i16 qb_cint(double v)
{
    double r = round_even(v);
    if (!(r >= -32768.0 && r <= 32767.0)) { qb_error(6); return 0; }
    return (qb_i16)r;
}
qb_i32 qb_clng(double v)
{
    double r = round_even(v);
    if (!(r >= -2147483648.0 && r <= 2147483647.0)) { qb_error(6); return 0; }
    return (qb_i32)r;
}
float qb_csng(double v)
{
    if (fabs(v) > 3.402823466e38 && !isinf(v)) { qb_error(6); return 0; }
    return (float)v;
}
double qb_ovf_s(double v) { if (isinf(v) || isnan(v)) { qb_error(6); return 0; } return v; }
double qb_int(double v) { return floor(v); }
double qb_fix(double v) { return trunc(v); }
qb_i32 qb_idiv(qb_i32 a, qb_i32 b)
{
    if (b == 0) { qb_error(11); return 0; }
    if (a == (-2147483647 - 1) && b == -1) { qb_error(6); return 0; }
    return a / b;
}
qb_i32 qb_imod(qb_i32 a, qb_i32 b)
{
    if (b == 0) { qb_error(11); return 0; }
    if (b == -1) return 0;
    return a % b;
}
double qb_fdiv(double a, double b)
{
    if (b == 0) { qb_error(11); return a == 0 ? 0 : (a < 0 ? -1.7976931348623157e308 : 1.7976931348623157e308); }
    return a / b;
}
float qb_fdivs(float a, float b)
{
    if (b == 0) { qb_error(11); return a == 0 ? 0 : (a < 0 ? -3.402823466e38f : 3.402823466e38f); }
    return a / b;
}
double qb_pow(double a, double b)
{
    if (a == 0 && b < 0) { qb_error(11); return 1.7976931348623157e308; }
    if (a < 0 && b != floor(b)) { qb_error(5); return 0; }
    double r = pow(a, b);
    if (isinf(r)) { qb_error(6); return 0; }
    return r;
}
double qb_sqr(double v) { if (v < 0) { qb_error(5); return 0; } return sqrt(v); }
double qb_log(double v) { if (v <= 0) { qb_error(5); return 0; } return log(v); }
double qb_exp(double v) { double r = exp(v); if (isinf(r)) { qb_error(6); return 0; } return r; }
double qb_sin(double v) { return sin(v); }
double qb_cos(double v) { return cos(v); }
double qb_tan(double v) { return tan(v); }
double qb_atn(double v) { return atan(v); }
double qb_abs(double v) { return fabs(v); }
qb_i32 qb_sgn(double v) { return v > 0 ? 1 : v < 0 ? -1 : 0; }

/* QB 4.5 compatible random number generator */
static uint32_t rnd_seed = 0x50000;
static float rnd_last;
float qb_rnd(float n)
{
    if (n == 0 && rnd_last != 0) return rnd_last;
    if (n < 0) {
        uint32_t m; memcpy(&m, &n, 4);
        rnd_seed = ((m & 0xFFFFFF) + ((m >> 24) & 0xFF)) & 0xFFFFFF;
    }
    if (n == 0 && rnd_last == 0) { /* RND(0) before any RND: returns based on current seed */
        return (float)rnd_seed / 16777216.0f;
    }
    rnd_seed = (rnd_seed * 16598013u + 12820163u) & 0xFFFFFF;
    rnd_last = (float)rnd_seed / 16777216.0f;
    return rnd_last;
}
void qb_randomize(double seed)
{
    uint64_t b; memcpy(&b, &seed, 8);
    uint32_t hi = (uint32_t)(b >> 32);
    uint32_t h = (hi ^ (hi >> 16)) & 0xFFFF;
    rnd_seed = (rnd_seed & 0xFF) | (h << 8);
}
void qb_randomize_ask(void)
{
    qb_in_begin(0, qb_slit("Random-number seed (-32768 to 32767)", 36), 0, "d");
    double d = 0; qb_in_d(&d); qb_in_end();
    qb_randomize(d);
}

double qb_now(void)
{
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}
void qb_msleep(int ms) { if (ms <= 0) return; struct timespec ts = { ms / 1000, (ms % 1000) * 1000000L }; nanosleep(&ts, NULL); }

float qb_timer(void)
{
    struct timeval tv; gettimeofday(&tv, NULL);
    time_t t = tv.tv_sec; struct tm tm; localtime_r(&t, &tm);
    double s = tm.tm_hour * 3600 + tm.tm_min * 60 + tm.tm_sec + tv.tv_usec / 1e6;
    /* QB resolution is one timer tick (1/18.2 s) */
    s = floor(s * 18.2065) / 18.2065;
    return (float)s;
}

/* ------------------------------------------------------------------ */
/* errors                                                              */
static const struct { int code; const char *msg; } errtab[] = {
    {1, "NEXT without FOR"}, {2, "Syntax error"}, {3, "RETURN without GOSUB"}, {4, "Out of DATA"},
    {5, "Illegal function call"}, {6, "Overflow"}, {7, "Out of memory"}, {8, "Label not defined"},
    {9, "Subscript out of range"}, {10, "Duplicate definition"}, {11, "Division by zero"},
    {12, "Illegal in direct mode"}, {13, "Type mismatch"}, {14, "Out of string space"},
    {16, "String formula too complex"}, {17, "Cannot continue"}, {18, "Function not defined"},
    {19, "No RESUME"}, {20, "RESUME without error"}, {24, "Device timeout"}, {25, "Device fault"},
    {26, "FOR without NEXT"}, {27, "Out of paper"}, {29, "WHILE without WEND"}, {30, "WEND without WHILE"},
    {33, "Duplicate label"}, {35, "Subprogram not defined"}, {37, "Argument-count mismatch"},
    {38, "Array not defined"}, {39, "CASE ELSE expected"}, {40, "Variable required"},
    {50, "FIELD overflow"}, {51, "Internal error"}, {52, "Bad file name or number"},
    {53, "File not found"}, {54, "Bad file mode"}, {55, "File already open"},
    {56, "FIELD statement active"}, {57, "Device I/O error"}, {58, "File already exists"},
    {59, "Bad record length"}, {61, "Disk full"}, {62, "Input past end of file"},
    {63, "Bad record number"}, {64, "Bad file name"}, {67, "Too many files"},
    {68, "Device unavailable"}, {69, "Communication-buffer overflow"}, {70, "Permission denied"},
    {71, "Disk not ready"}, {72, "Disk-media error"}, {73, "Advanced feature unavailable"},
    {74, "Rename across disks"}, {75, "Path/File access error"}, {76, "Path not found"},
    {0, NULL}
};

const char *qb_errmsg(int code)
{
    for (int i = 0; errtab[i].msg; i++) if (errtab[i].code == code) return errtab[i].msg;
    return "Unprintable error";
}

static void fatal_error(int code)
{
    char msg[256];
    const char *m = qb_errmsg(code);
    if (qb_curline > 0)
        snprintf(msg, sizeof msg, "%s in line %d of module %s", m, qb_curline, qb_module_name);
    else
        snprintf(msg, sizeof msg, "%s in module %s", m, qb_module_name);
    fprintf(stderr, "qbrt: runtime error %d: %s\n", code, msg);
    fflush(stderr);
    if (qb_mode_display != QBD_STREAM) {
        qb_errpend = 0; qb_handler_on = 0;
        qbs_newline();
        qbs_write(msg, strlen(msg));
        qbs_newline();
        if (qb_mode_display == QBD_WINDOW || qb_mode_display == QBD_CONSOLE) {
            const char *h = "Hit any key to return to system";
            qbs_write(h, strlen(h));
            qbd_flush();
            qbsnd_shutdown();
            qbd_shutdown(1);
        } else qbd_shutdown(0);
    } else qbd_shutdown(0);
    qbf_close_all();
    _exit(code > 255 ? 255 : code);
}

void qb_error(qb_i32 code)
{
    if (qb_errpend) return;        /* already unwinding */
    qb_err = code;
    qb_errline = qb_curline;
    if (qb_handler_on && !qb_in_handler) { qb_errpend = 1; return; }
    fatal_error(code);
}

void qb_error_stmt(double code)
{
    int c = qb_cint(code);
    if (c < 1 || c > 255) { qb_error(5); return; }
    qb_error(c);
}

void qb_fatal_check(void) { if (qb_errpend && !qb_handler_on) fatal_error(qb_err); }
qbs qb_erdev_s(void) { return qb_slit("", 0); }
qb_i32 qb_erdev(void) { return 0; }

/* ------------------------------------------------------------------ */
/* DATA / READ                                                         */
static const char *const *data_items;
static qb_i32 data_n, data_pos;
void qb_data_init(const char *const *items, qb_i32 n) { data_items = items; data_n = n; data_pos = 0; }
void qb_restore(qb_i32 idx) { data_pos = idx < 0 ? 0 : idx; }

static const char *data_next(void)
{
    if (data_pos >= data_n) { qb_error(4); return NULL; }
    return data_items[data_pos++];
}
qbs qb_read_s(void)
{
    const char *d = data_next();
    if (!d) return qb_slit("", 0);
    int n = strlen(d);
    if (n >= 1 && d[0] == '"') {
        int e = n - 1; if (e < 1 || d[e] != '"') e = n;
        qbs r = qb_stmp(e - 1); memcpy(r.p, d + 1, e - 1); return r;
    }
    /* unquoted: trim blanks */
    int a = 0, b = n; while (a < b && d[a] == ' ') a++; while (b > a && d[b - 1] == ' ') b--;
    qbs r = qb_stmp(b - a); memcpy(r.p, d + a, b - a); return r;
}
double qb_read_d(void)
{
    const char *d = data_next();
    if (!d) return 0;
    const char *p = d; while (*p == ' ') p++;
    if (!*p) return 0;
    double v; int used;
    if (*p == '"' || !qb_parse_number(p, strlen(p), &v, &used)) { qb_error(2); return 0; }
    const char *q = p + used; while (*q == ' ') q++;
    if (*q) { qb_error(2); return 0; }
    return v;
}

/* ------------------------------------------------------------------ */
/* program control                                                     */
static void (*chain_restart)(void);
void qb_set_chain_restart(void (*fn)(void)) { chain_restart = fn; }

void qb_init(int argc, char **argv, const char *module, qb_i32 flags)
{
    g_argc = argc; g_argv = argv; qb_rt_flags = flags;
    snprintf(qb_module_name, sizeof qb_module_name, "%s", module);
    setvbuf(stdout, NULL, _IOFBF, 1 << 16);
    qbm_init();
    qbs_init();
    qbd_init();
    qbsnd_init();
}

static void finish(int wait)
{
    qbsnd_wait_idle();
    qbsnd_shutdown();
    qbf_close_all();
    qbd_shutdown(wait);
    fflush(stdout);
}
void qb_end(void) { finish(1); _exit(0); }
void qb_system(void) { finish(0); _exit(0); }
void qb_stop(void)
{
    char msg[128];
    snprintf(msg, sizeof msg, "Stop in line %d of module %s", qb_curline, qb_module_name);
    if (qb_mode_display != QBD_STREAM) { qbs_newline(); qbs_write(msg, strlen(msg)); qbs_newline(); }
    else fprintf(stderr, "%s\n", msg);
    finish(1); _exit(0);
}

void qb_sleep(qb_i32 secs)
{
    qbd_flush();
    double end = secs == QB_NA || secs <= 0 ? 1e300 : qb_now() + secs;
    /* SLEEP returns on any key press (key is not consumed in QB 4.5? it is left in the buffer) */
    for (;;) {
        int k = qbd_getkey(0);
        if (k >= 0) { qbd_key_push(k); break; }
        if (qb_now() >= end) break;
        if (qb_evflag) break;
        if (qb_mode_display == QBD_HEADLESS || (qb_mode_display == QBD_STREAM && !qb_line_tty)) { if (secs == QB_NA || secs <= 0) break; }
        qb_msleep(10);
    }
}

void qb_shell(qbs cmd, qb_i32 has)
{
    qbd_flush();
    fflush(stdout);
    char *c;
#ifdef _WIN32
    if (!has || cmd.len == 0) { const char *cs = getenv("COMSPEC"); c = (char *)(cs ? cs : "cmd.exe"); }
    else {
        c = qb_cstr(cmd);
        char *t = c; while (*t == ' ') t++;
        if (!strncasecmp(t, "CLS", 3) && !t[3]) { qb_cls(QB_NA); return; }
    }
    int was_console = qb_mode_display == QBD_CONSOLE;
    if (was_console) qbd_console_suspend(1);
    int rc = system(c);
    if (was_console) qbd_console_suspend(0);
    (void)rc;
#else
    if (!has || cmd.len == 0) c = "${SHELL:-/bin/sh}";
    else {
        c = qb_cstr(cmd);
        /* translate a few DOS commands */
        char *t = c; while (*t == ' ') t++;
        if (!strncasecmp(t, "DIR", 3) && (t[3] == ' ' || !t[3])) {
            qbs r = qb_sadd(qb_slit("ls -l ", 6), qb_slit(t + 3, strlen(t + 3)));
            c = qb_cstr(r);
        } else if (!strncasecmp(t, "CLS", 3) && !t[3]) { qb_cls(QB_NA); return; }
    }
    int rc = system(c);
    (void)rc;
#endif
}

void qb_chain(qbs prog) { qb_run_file(prog); }
#ifdef _WIN32
void qb_run_file(qbs prog)
{
    char *p = qb_cstr(prog); char path[4096], cand[4096];
    qb_path_from_dos(p, path, sizeof path);
    char *dot = strrchr(path, '.');
    char *slash = strrchr(path, '\\'); char *s2 = strrchr(path, '/'); if (s2 > slash) slash = s2;
    if (dot && (!slash || dot > slash) && (!strcasecmp(dot, ".bas") || !strcasecmp(dot, ".exe"))) *dot = 0;
    if (!slash && !strchr(path, ':')) {
        char self[MAX_PATH]; DWORD n = GetModuleFileNameA(NULL, self, sizeof self);
        char *e = n ? strrchr(self, '\\') : NULL;
        if (e) { *e = 0; snprintf(cand, sizeof cand, "%s\\%s.exe", self, path); }
        else snprintf(cand, sizeof cand, "%s.exe", path);
    } else snprintf(cand, sizeof cand, "%s.exe", path);
    FILE *f = fopen(cand, "rb");
    if (!f) { qb_error(53); return; }
    fclose(f);
    { extern void qb__save_common(void); qb__save_common(); }
    qbd_flush();
    finish(0);
    setenv("QB_CHAINED", "1", 1);
    char quoted[4200]; snprintf(quoted, sizeof quoted, "\"%s\"", cand);
    const char *av[] = { quoted, NULL };
    fflush(NULL);
    intptr_t rc = _spawnv(_P_WAIT, cand, av);
    _exit(rc < 0 ? 53 : (int)rc);
}
#else
void qb_run_file(qbs prog)
{
    char *p = qb_cstr(prog); char path[4096], res[4096];
    qb_path_from_dos(p, path, sizeof path);
    char *dot = strrchr(path, '.');
    char *slash = strrchr(path, '/');
    if (dot && (!slash || dot > slash) && (!strcasecmp(dot, ".bas") || !strcasecmp(dot, ".exe"))) *dot = 0;
    /* look for an executable next to us */
    char cand[4096];
    if (!strchr(path, '/')) {
        char self[4096]; ssize_t n = readlink("/proc/self/exe", self, sizeof self - 1);
        if (n > 0) { self[n] = 0; char *s = strrchr(self, '/'); if (s) *s = 0; snprintf(cand, sizeof cand, "%s/%s", self, path); }
        else snprintf(cand, sizeof cand, "%s", path);
    } else snprintf(cand, sizeof cand, "%s", path);
    FILE *f = qb_fopen_ci(cand, "rb", res, sizeof res);
    if (!f) { qb_error(53); return; }
    fclose(f);
    { extern void qb__save_common(void); qb__save_common(); }
    qbd_flush();
    finish(0);
    char *av[] = { res, NULL };
    setenv("QB_CHAINED", "1", 1);
    execv(res, av);
    _exit(53);
}
#endif

qb_i32 qb_chained(void) { return getenv("QB_CHAINED") != NULL; }

/* COMMON values are handed over through a temporary file named in the environment */
static FILE *common_out, *common_in;
void qb_common_save(qb_i32 idx, qb_i32 type, void *p, qb_i32 size)
{
    if (!common_out) {
        char path[512];
#ifdef _WIN32
        char tmpdir[MAX_PATH]; if (!GetTempPathA(sizeof tmpdir, tmpdir)) strcpy(tmpdir, ".\\");
        snprintf(path, sizeof path, "%slinbasic-common-%d.bin", tmpdir, (int)getpid());
#else
        snprintf(path, sizeof path, "/tmp/linbasic-common-%d.bin", (int)getpid());
#endif
        common_out = fopen(path, "wb"); if (!common_out) return;
        setenv("QB_COMMON", path, 1);
    }
    if (type == 1) {   /* string */
        qbs *s = p; fwrite(&s->len, 4, 1, common_out); fwrite(s->p ? s->p : "", 1, s->len, common_out);
    } else if (type == 2) { /* array */
        qbarr *a = p; fwrite(a, sizeof *a, 1, common_out);
        if (a->data) {
            if (a->kind == 1) { qbs *s = (qbs *)a->data; for (int i = 0; i < a->n; i++) { fwrite(&s[i].len, 4, 1, common_out); fwrite(s[i].p ? s[i].p : "", 1, s[i].len, common_out); } }
            else fwrite(a->data, a->esz, a->n, common_out);
        }
    } else fwrite(p, 1, size, common_out);
    fflush(common_out);
    (void)idx;
}
void qb_common_load(qb_i32 idx, qb_i32 type, void *p, qb_i32 size)
{
    (void)idx;
    if (!common_in) { const char *path = getenv("QB_COMMON"); if (!path) return; common_in = fopen(path, "rb"); if (!common_in) return; unlink(path); unsetenv("QB_COMMON"); }
    if (type == 1) {
        qb_i32 n = 0; if (fread(&n, 4, 1, common_in) != 1) return;
        qbs t = qb_stmp(n); if (n && fread(t.p, 1, n, common_in) != (size_t)n) return; qb_sset((qbs *)p, t);
    } else if (type == 2) {
        qbarr *a = p, h; if (fread(&h, sizeof h, 1, common_in) != 1) return;
        qb_afree(a); *a = h; a->data = NULL;
        if (h.data) {
            a->data = calloc(h.n, h.esz);
            if (h.kind == 1) { qbs *s = (qbs *)a->data; for (int i = 0; i < h.n; i++) { qb_i32 n = 0; if (fread(&n, 4, 1, common_in) != 1) return; qbs t = qb_stmp(n); if (n && fread(t.p, 1, n, common_in) != (size_t)n) return; qb_sset(&s[i], t); } }
            else if (fread(a->data, h.esz, h.n, common_in) != (size_t)h.n) return;
        }
    } else { if (fread(p, 1, size, common_in) != (size_t)size) return; }
}

void qb_clear(void) { qb_close_all(); }
double qb_fre(double x) { (void)x; return 524288.0; }
void qb_tron(qb_i32 on) { (void)on; }

/* ------------------------------------------------------------------ */
/* event trapping                                                      */
static int ev_state[QB_EV_N];      /* 0 off, 1 on, 2 stop */
static int ev_has[QB_EV_N];
static volatile int ev_pend[QB_EV_N];
static int ev_inside[QB_EV_N];
static double timer_interval, timer_next;
static int play_threshold;
static int user_keys[32][2];       /* KEY 15..25 definitions: shift, scan */
static int user_key_defined[32];

void qb_ev_set(qb_i32 ev, qb_i32 state)
{
    if (ev < 0 || ev >= QB_EV_N) return;
    if (ev == QB_EV_KEY) { for (int i = 1; i <= 31; i++) qb_ev_set(i, state); return; }
    ev_state[ev] = state;
    if (ev == QB_EV_TIMER && state == 1 && timer_interval > 0 && timer_next == 0) timer_next = qb_now() + timer_interval;
    if (state == 1 && ev_pend[ev]) qb_evflag = 1;
    if (state == 0) ev_pend[ev] = 0;
}
void qb_ev_handler(qb_i32 ev, qb_i32 has)
{
    if (ev == QB_EV_KEY) { for (int i = 1; i <= 31; i++) ev_has[i] = has; return; }
    if (ev >= 0 && ev < QB_EV_N) ev_has[ev] = has;
}
void qb_ev_timer(double secs) { timer_interval = secs; timer_next = qb_now() + secs; }
void qb_ev_play(qb_i32 n) { play_threshold = n; }

void qb_poll_events(void)
{
    if (ev_state[QB_EV_TIMER] && ev_has[QB_EV_TIMER] && timer_interval > 0) {
        double t = qb_now();
        if (timer_next == 0) timer_next = t + timer_interval;
        if (t >= timer_next) { timer_next = t + timer_interval; ev_pend[QB_EV_TIMER] = 1; }
    }
    if (ev_state[QB_EV_PLAY] && ev_has[QB_EV_PLAY]) {
        static int last = 0; int q = qbsnd_queue_notes();
        if (last >= play_threshold && q < play_threshold) ev_pend[QB_EV_PLAY] = 1;
        last = q;
    }
    for (int i = 0; i < QB_EV_N; i++) if (ev_pend[i] && ev_state[i] == 1 && ev_has[i] && !ev_inside[i]) { qb_evflag = 1; return; }
}

qb_i32 qb_ev_take(void)
{
    qb_evflag = 0;
    qb_poll_events();
    qb_evflag = 0;
    for (int i = 0; i < QB_EV_N; i++)
        if (ev_pend[i] && ev_state[i] == 1 && ev_has[i] && !ev_inside[i]) { ev_pend[i] = 0; return i + 1; }
    return 0;
}
void qb_ev_enter(qb_i32 ev) { ev_inside[ev] = 1; }
void qb_ev_leave(qb_i32 ev) { ev_inside[ev] = 0; qb_poll_events(); }

/* key trapping: key is (ascii) or 0x100|scan; shift state from display */
static int key_index(int key)
{
    if (!(key & 0x100)) return 0;
    int sc = key & 0xFF;
    if (sc >= 59 && sc <= 68) return sc - 58;      /* F1..F10 -> 1..10 */
    if (sc == 72) return 11; if (sc == 75) return 12; if (sc == 77) return 13; if (sc == 80) return 14;
    if (sc == 133) return 30; if (sc == 134) return 31;
    return 0;
}
int qb_ev_key_trapped(int key)
{
    int idx = key_index(key);
    int sc = (key & 0x100) ? key & 0xFF : -1;
    for (int u = 15; u <= 25 && idx == 0; u++)
        if (user_key_defined[u] && sc >= 0 && user_keys[u][1] == sc) idx = u;
    if (!idx) return 0;
    if (ev_state[idx] == 0 || !ev_has[idx]) return 0;
    ev_pend[idx] = 1;
    if (ev_state[idx] == 1) qb_evflag = 1;
    return 1;
}
void qb_ev_key_trap(int key) { (void)qb_ev_key_trapped(key); }

void qb_key_set(qb_i32 n, qbs s)
{
    if (n >= 15 && n <= 25 && s.len >= 2) { user_keys[n][0] = (unsigned char)s.p[0]; user_keys[n][1] = (unsigned char)s.p[1]; user_key_defined[n] = 1; }
}

static void (*common_saver)(void);
void qb_set_common_saver(void (*f)(void)) { common_saver = f; }
void qb__save_common(void) { if (common_saver) common_saver(); }

/* box a string value so it can be passed by reference to a SUB/FUNCTION */
qbs *qb_sbox(qbs s)
{
    qbs *b = malloc(sizeof(qbs));
    if (!b) oom();
    *b = s;
    tmp_push((char *)b);
    return b;
}
