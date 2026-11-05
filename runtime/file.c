/* file.c - OPEN/CLOSE, sequential, random and binary files, directories.
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */
#include "qbrt_int.h"
#include <ctype.h>
#include <sys/stat.h>
#include <errno.h>
#ifndef _WIN32
#include <dirent.h>
#include <fnmatch.h>
#include <unistd.h>
#endif

struct qbfile {
    FILE *f;
    int mode, access;
    int reclen;
    int col, width;
    char *recbuf;
    int lastrec;           /* RANDOM: last record accessed */
    long lastpos;          /* BINARY: last byte position   */
    int eofflag;
    int unget;
    long seqbytes;
    char path[1024];
};

#define QB_MAXFILES 256
static qbfile files[QB_MAXFILES];

/* ---- DOS path translation, case-insensitive lookup ------------------ */
#ifdef _WIN32
#define NULDEV "NUL"
/* Windows understands DOS paths natively: only trim the blanks */
void qb_path_from_dos(const char *in, char *out, int size)
{
    while (*in == ' ') in++;
    int o = 0;
    for (; *in && o < size - 1; in++) out[o++] = *in;
    while (o > 0 && out[o - 1] == ' ') o--;
    out[o] = 0;
}

static int resolve_ci(const char *path, char *out, int size)
{
    struct stat st;
    snprintf(out, size, "%s", path);
    return stat(path, &st) == 0;
}
#else
#define NULDEV "/dev/null"
void qb_path_from_dos(const char *in, char *out, int size)
{
    int o = 0;
    const char *p = in;
    while (*p == ' ') p++;
    if (isalpha((unsigned char)p[0]) && p[1] == ':') p += 2;
    for (; *p && o < size - 1; p++) out[o++] = *p == '\\' ? '/' : *p;
    while (o > 0 && out[o - 1] == ' ') o--;
    out[o] = 0;
}

static int resolve_ci(const char *path, char *out, int size)
{
    /* resolve each component case-insensitively; returns 1 if the full path exists */
    char work[4096]; snprintf(work, sizeof work, "%s", path);
    char cur[4096];
    if (work[0] == '/') { strcpy(cur, "/"); } else { strcpy(cur, ""); }
    char *save = NULL;
    char *tok = strtok_r(work, "/", &save);
    int ok = 1;
    while (tok) {
        char *next = strtok_r(NULL, "/", &save);
        char cand[4096];
        snprintf(cand, sizeof cand, "%s%s%s", cur, (cur[0] && strcmp(cur, "/")) ? "/" : "", tok);
        struct stat st;
        if (stat(cand, &st) != 0) {
            DIR *d = opendir(cur[0] ? cur : ".");
            int found = 0;
            if (d) {
                struct dirent *e;
                while ((e = readdir(d))) if (strcasecmp(e->d_name, tok) == 0) {
                    snprintf(cand, sizeof cand, "%s%s%s", cur, (cur[0] && strcmp(cur, "/")) ? "/" : "", e->d_name);
                    found = 1; break;
                }
                closedir(d);
            }
            if (!found) ok = 0;
        }
        strcpy(cur, cand);
        tok = next;
    }
    snprintf(out, size, "%s", cur[0] ? cur : path);
    return ok;
}
#endif

FILE *qb_fopen_ci(const char *name, const char *mode, char *resolved, int rsize)
{
    char buf[4096];
    FILE *f = fopen(name, mode);
    if (f) { if (resolved) snprintf(resolved, rsize, "%s", name); return f; }
    if (resolve_ci(name, buf, sizeof buf) || mode[0] != 'r') {
        f = fopen(buf, mode);
        if (f && resolved) snprintf(resolved, rsize, "%s", buf);
    }
    return f;
}

static void dos_name(qbs name, char *out, int size)
{
    char *c = qb_cstr(name);
    char tmp[4096];
    qb_path_from_dos(c, tmp, sizeof tmp);
    /* existing file with different case? */
    char res[4096];
    if (resolve_ci(tmp, res, sizeof res)) snprintf(out, size, "%s", res);
    else {
        /* resolve the directory part at least */
        char *sl = strrchr(tmp, '/');
        if (sl) {
            *sl = 0; char d[4096];
            if (resolve_ci(tmp, d, sizeof d)) snprintf(out, size, "%s/%s", d, sl + 1);
            else { *sl = '/'; snprintf(out, size, "%s", tmp); }
        } else snprintf(out, size, "%s", tmp);
    }
}

/* ---- device names ----------------------------------------------------- */
static int is_device(const char *n, const char *dev)
{
    size_t l = strlen(dev);
    return strncasecmp(n, dev, l) == 0 && (n[l] == 0 || n[l] == ':');
}

qbfile *qbf_get(int n, int needmode)
{
    if (n < 1 || n >= QB_MAXFILES) { qb_error(52); return NULL; }
    qbfile *q = &files[n];
    if (!q->f) { qb_error(52); return NULL; }
    if (needmode == 1 && q->mode != QB_M_INPUT && q->mode != QB_M_RANDOM && q->mode != QB_M_BINARY) { qb_error(54); return NULL; }
    if (needmode == -2 && q->mode == QB_M_INPUT) { qb_error(54); return NULL; }
    return q;
}

void qb_open(qbs name, qb_i32 mode, qb_i32 access, qb_i32 lock, qb_i32 fileno, qb_i32 reclen)
{
    (void)lock;
    if (fileno < 1 || fileno >= QB_MAXFILES) { qb_error(52); return; }
    qbfile *q = &files[fileno];
    if (q->f) { qb_error(55); return; }
    if (name.len == 0) { qb_error(64); return; }
    if (mode == QB_NA || mode == 0) mode = QB_M_RANDOM;
    char path[4096];
    char *raw = qb_cstr(name);
    while (*raw == ' ') raw++;
    FILE *f = NULL;
    if (is_device(raw, "SCRN") || is_device(raw, "CONS")) { f = stdout; }
    else if (is_device(raw, "KYBD")) { f = stdin; }
    else if (is_device(raw, "LPT1") || is_device(raw, "LPT2") || is_device(raw, "LPT3") || is_device(raw, "PRN")) {
        const char *lp = getenv("QB_LPT"); f = fopen(lp ? lp : NULDEV, "a");
    } else if (is_device(raw, "COM1") || is_device(raw, "COM2")) { qb_error(68); return; }
    else if (is_device(raw, "NUL")) f = fopen(NULDEV, mode == QB_M_INPUT ? "r" : "w");
    else {
        dos_name(name, path, sizeof path);
        switch (mode) {
        case QB_M_INPUT:
            f = fopen(path, "rb");
            if (!f) { struct stat st; qb_error(stat(path, &st) == 0 ? 75 : (errno == ENOENT ? 53 : 75)); return; }
            break;
        case QB_M_OUTPUT: f = fopen(path, "wb"); break;
        case QB_M_APPEND: f = fopen(path, "ab"); if (f) fseek(f, 0, SEEK_END); break;
        default:
            if (access == 1) f = fopen(path, "rb");
            else {
                f = fopen(path, "r+b");
                if (!f && access != 1) f = fopen(path, "w+b");
                if (!f && access == QB_NA) f = fopen(path, "rb");
            }
            break;
        }
        if (!f) {
            if (errno == EACCES || errno == EISDIR) qb_error(75);
            else if (errno == ENOENT) qb_error(76);
            else qb_error(75);
            return;
        }
    }
    memset(q, 0, sizeof *q);
    q->f = f; q->mode = mode; q->access = access;
    q->reclen = (reclen == QB_NA || reclen <= 0) ? 128 : reclen;
    if (reclen != QB_NA && (reclen < 1 || reclen > 32767)) { fclose(f); q->f = NULL; qb_error(59); return; }
    q->width = 255;
    q->unget = -1;
    snprintf(q->path, sizeof q->path, "%s", path);
    if (mode == QB_M_RANDOM) q->recbuf = calloc(1, q->reclen);
}

void qb_open_old(qbs m, qb_i32 fileno, qbs name, qb_i32 reclen)
{
    int mode = 0;
    char c = m.len ? toupper((unsigned char)m.p[0]) : 0;
    switch (c) { case 'I': mode = QB_M_INPUT; break; case 'O': mode = QB_M_OUTPUT; break; case 'A': mode = QB_M_APPEND; break;
                 case 'R': mode = QB_M_RANDOM; break; case 'B': mode = QB_M_BINARY; break; default: qb_error(54); return; }
    qb_open(name, mode, QB_NA, QB_NA, fileno, reclen);
}

static void close_one(int n)
{
    qbfile *q = &files[n];
    if (!q->f) return;
    if (q->f != stdout && q->f != stdin) fclose(q->f); else fflush(q->f);
    free(q->recbuf);
    memset(q, 0, sizeof *q);
}
void qb_close(qb_i32 n)
{
    if (n < 1 || n >= QB_MAXFILES) { qb_error(52); return; }
    close_one(n);
}
void qb_close_all(void) { for (int i = 1; i < QB_MAXFILES; i++) close_one(i); }
void qbf_close_all(void) { qb_close_all(); }

qb_i32 qb_freefile(void)
{
    for (int i = 1; i < QB_MAXFILES; i++) if (!files[i].f) return i;
    qb_error(67); return 0;
}

int qbf_getc(int n)
{
    qbfile *q = &files[n];
    if (!q->f) return -1;
    if (q->unget >= 0) { int c = q->unget; q->unget = -1; return c; }
    int c = getc(q->f);
    if (c == EOF) return -1;
    q->seqbytes++;
    return c;
}
void qbf_ungetc(int n, int c) { files[n].unget = c; }

int qbf_eof_raw(int n)
{
    qbfile *q = &files[n];
    if (q->unget >= 0) return q->unget == 0x1A;
    int c = getc(q->f);
    if (c == EOF) return 1;
    ungetc(c, q->f);
    return c == 0x1A;
}

void qbf_write(int n, const char *s, int len)
{
    qbfile *q = &files[n];
    if (!q->f) return;
    if (q->mode == QB_M_INPUT) { qb_error(54); return; }
    if (q->mode == QB_M_RANDOM) {
        /* PRINT # to a random file writes into the record buffer (rare); write directly */
    }
    if (fwrite(s, 1, len, q->f) != (size_t)len) { qb_error(61); return; }
    for (int i = 0; i < len; i++) {
        if (s[i] == '\n') q->col = 0;
        else if (s[i] != '\r') q->col++;
    }
    if (q->f == stdout) fflush(stdout);
}
int qbf_col(int n) { return files[n].col; }
int qbf_width(int n) { return files[n].width; }

qb_i32 qb_eof(qb_i32 n)
{
    qbfile *q = qbf_get(n, 0);
    if (!q) return 0;
    if (q->mode == QB_M_INPUT) return qbf_eof_raw(n) ? -1 : 0;
    if (q->mode == QB_M_OUTPUT || q->mode == QB_M_APPEND) { qb_error(54); return 0; }
    return q->eofflag ? -1 : 0;
}

qb_i32 qb_lof(qb_i32 n)
{
    qbfile *q = qbf_get(n, 0);
    if (!q) return 0;
    fflush(q->f);
    struct stat st;
    if (fstat(fileno(q->f), &st) != 0) return 0;
    return (qb_i32)st.st_size;
}

qb_i32 qb_loc(qb_i32 n)
{
    qbfile *q = qbf_get(n, 0);
    if (!q) return 0;
    if (q->mode == QB_M_RANDOM) return q->lastrec;
    long p = ftell(q->f);
    if (q->mode == QB_M_BINARY) return (qb_i32)p;
    if (q->mode == QB_M_INPUT) return (qb_i32)(p / 128 + (p % 128 ? 1 : 0));
    return (qb_i32)(p / 128 + (p % 128 ? 1 : 0));
}

qb_i32 qb_seek_fn(qb_i32 n)
{
    qbfile *q = qbf_get(n, 0);
    if (!q) return 0;
    long p = ftell(q->f);
    if (q->mode == QB_M_RANDOM) return (qb_i32)(p / q->reclen + 1);
    return (qb_i32)(p + 1);
}

void qb_seek(qb_i32 n, qb_i32 pos)
{
    qbfile *q = qbf_get(n, 0);
    if (!q) return;
    if (pos < 1) { qb_error(63); return; }
    q->unget = -1;
    long off = q->mode == QB_M_RANDOM ? (long)(pos - 1) * q->reclen : pos - 1;
    fseek(q->f, off, SEEK_SET);
    q->eofflag = 0;
}

void qb_get(qb_i32 n, qb_i32 rec, void *var, qb_i32 size, qb_i32 isstr)
{
    qbfile *q = qbf_get(n, 0);
    if (!q) return;
    if (q->mode != QB_M_RANDOM && q->mode != QB_M_BINARY) { qb_error(54); return; }
    if (rec != QB_NA) {
        if (rec < 1) { qb_error(63); return; }
        long off = q->mode == QB_M_RANDOM ? (long)(rec - 1) * q->reclen : rec - 1;
        fseek(q->f, off, SEEK_SET);
    }
    long pos = ftell(q->f);
    char *dst; int len;
    qbs *s = NULL;
    if (q->mode == QB_M_RANDOM) {
        /* QB 4.5: a variable-length string is stored as a 2-byte length followed by its bytes */
        if (!var) { dst = q->recbuf; len = q->reclen; }
        else if (isstr) { s = var; if (q->reclen < 2) { qb_error(59); return; } len = 0; dst = NULL; }
        else { if (size > q->reclen) { qb_error(59); return; } dst = var; len = size; }
        char *buf = q->recbuf;
        size_t got = fread(buf, 1, q->reclen, q->f);
        if (got < (size_t)q->reclen) { memset(buf + got, 0, q->reclen - got); q->eofflag = 1; } else q->eofflag = 0;
        if (got < (size_t)q->reclen) fseek(q->f, pos + q->reclen, SEEK_SET);
        q->lastrec = (int)(pos / q->reclen) + 1;
        if (var && !isstr) memcpy(dst, buf, len);
        if (s) {
            len = (unsigned char)buf[0] | (unsigned char)buf[1] << 8;
            if (len > q->reclen - 2) { qb_error(59); return; }
            if (s->flags & 2) { int k = len < s->len ? len : s->len; memcpy(s->p, buf + 2, k); memset(s->p + k, ' ', s->len - k); }
            else { qbs t = qb_stmp(len); memcpy(t.p, buf + 2, len); qb_sset(s, t); }
        }
    } else {
        if (!var) { qb_error(5); return; }
        if (isstr) {
            s = var; len = s->len;
            qbs t = qb_stmp(len);
            size_t got = fread(t.p, 1, len, q->f);
            if (got < (size_t)len) { memset(t.p + got, 0, len - got); q->eofflag = 1; } else q->eofflag = 0;
            if (s->flags & 2) memcpy(s->p, t.p, len); else qb_sset(s, t);
        } else {
            size_t got = fread(var, 1, size, q->f);
            if (got < (size_t)size) { memset((char *)var + got, 0, size - got); q->eofflag = 1; } else q->eofflag = 0;
        }
        q->lastpos = ftell(q->f);
    }
}

void qb_put(qb_i32 n, qb_i32 rec, void *var, qb_i32 size, qb_i32 isstr)
{
    qbfile *q = qbf_get(n, 0);
    if (!q) return;
    if (q->mode != QB_M_RANDOM && q->mode != QB_M_BINARY) { qb_error(54); return; }
    if (q->access == 1) { qb_error(75); return; }
    if (rec != QB_NA) {
        if (rec < 1) { qb_error(63); return; }
        long off = q->mode == QB_M_RANDOM ? (long)(rec - 1) * q->reclen : rec - 1;
        fseek(q->f, 0, SEEK_END);
        long end = ftell(q->f);
        if (off > end) { /* extend with zeros */ static const char z[512]; long k = off - end; while (k > 0) { long c = k > 512 ? 512 : k; fwrite(z, 1, c, q->f); k -= c; } }
        fseek(q->f, off, SEEK_SET);
    }
    long pos = ftell(q->f);
    if (q->mode == QB_M_RANDOM) {
        char *buf = q->recbuf;
        int n = q->reclen;
        if (var) {
            /* QB 4.5 writes only the variable's bytes (the rest of the record is left alone);
               a variable-length string gets a 2-byte length in front of it */
            char *tmp = malloc(n + 2);
            if (!tmp) { qb_error(7); return; }
            if (isstr) {
                qbs *s = var;
                if (s->len + 2 > q->reclen) { free(tmp); qb_error(59); return; }
                tmp[0] = (char)(s->len & 0xFF); tmp[1] = (char)(s->len >> 8);
                if (s->len) memcpy(tmp + 2, s->p, s->len);
                n = s->len + 2;
            } else {
                if (size > q->reclen) { free(tmp); qb_error(59); return; }
                memcpy(tmp, var, size);
                n = size;
            }
            size_t w = fwrite(tmp, 1, n, q->f);
            free(tmp);
            if (w != (size_t)n) { qb_error(61); return; }
            fseek(q->f, pos + q->reclen, SEEK_SET);
        } else if (fwrite(buf, 1, n, q->f) != (size_t)n) { qb_error(61); return; }
        q->lastrec = (int)(pos / q->reclen) + 1;
    } else {
        if (!var) { qb_error(5); return; }
        if (isstr) { qbs *s = var; if (s->len) fwrite(s->p, 1, s->len, q->f); }
        else fwrite(var, 1, size, q->f);
        q->lastpos = ftell(q->f);
    }
    fflush(q->f);
}

void qb_field(qb_i32 n, qb_i32 offset, qb_i32 width, qbs *var)
{
    qbfile *q = qbf_get(n, 0);
    if (!q) return;
    if (q->mode != QB_M_RANDOM) { qb_error(54); return; }
    if (offset + width > q->reclen) { qb_error(50); return; }
    if ((var->flags & 1) && var->p) free(var->p);
    var->p = q->recbuf + offset; var->len = width; var->flags = 2;
}

/* ---- directories and misc ---------------------------------------------- */
static void split_pattern(qbs pat, char *dir, char *mask, int size)
{
    char tmp[4096]; char *c = qb_cstr(pat);
    qb_path_from_dos(c, tmp, sizeof tmp);
    char *sl = strrchr(tmp, '/');
#ifdef _WIN32
    { char *b = strrchr(tmp, '\\'); if (b > sl) sl = b; char *col = strrchr(tmp, ':'); if (col > sl) sl = col; }
    if (sl && *sl == ':') {   /* "C:*.BAS" - current directory of that drive */
        snprintf(mask, size, "%s", sl + 1); sl[1] = 0; snprintf(dir, size, "%s", tmp);
        if (!mask[0]) strcpy(mask, "*");
        if (!strcmp(mask, "*.*")) strcpy(mask, "*");
        return;
    }
    if (sl == tmp) { snprintf(mask, size, "%s", sl + 1); snprintf(dir, size, "\\"); if (!mask[0]) strcpy(mask, "*"); if (!strcmp(mask, "*.*")) strcpy(mask, "*"); return; }
#endif
    if (sl) { *sl = 0; char d[4096]; resolve_ci(tmp[0] ? tmp : "/", d, sizeof d); snprintf(dir, size, "%s", tmp[0] ? d : "/"); snprintf(mask, size, "%s", sl + 1); }
    else { snprintf(dir, size, "."); snprintf(mask, size, "%s", tmp); }
    if (!mask[0]) strcpy(mask, "*");
    /* DOS "*.*" also matches names without a dot */
    if (!strcmp(mask, "*.*")) strcpy(mask, "*");
}

void qb_kill(qbs pattern)
{
    char dir[4096], mask[1024];
    split_pattern(pattern, dir, mask, sizeof mask);
    DIR *d = opendir(dir);
    if (!d) { qb_error(76); return; }
    struct dirent *e; int n = 0;
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.' && (!e->d_name[1] || (e->d_name[1] == '.' && !e->d_name[2]))) continue;
        if (fnmatch(mask, e->d_name, FNM_CASEFOLD) == 0) {
            char p[8192]; snprintf(p, sizeof p, "%s/%s", dir, e->d_name);
            struct stat st; if (stat(p, &st) == 0 && S_ISDIR(st.st_mode)) continue;
            if (unlink(p) == 0) n++;
        }
    }
    closedir(d);
    if (!n) qb_error(53);
}

void qb_name(qbs from, qbs to)
{
    char a[4096], b[4096];
    dos_name(from, a, sizeof a); dos_name(to, b, sizeof b);
    struct stat st;
    if (stat(a, &st) != 0) { qb_error(53); return; }
    if (stat(b, &st) == 0) { qb_error(58); return; }
    if (rename(a, b) != 0) qb_error(errno == EXDEV ? 74 : 75);
}
void qb_mkdir(qbs d) { char p[4096]; dos_name(d, p, sizeof p); if (mkdir(p, 0777) != 0) qb_error(75); }
void qb_rmdir(qbs d) { char p[4096]; dos_name(d, p, sizeof p); if (rmdir(p) != 0) qb_error(errno == ENOENT ? 76 : 75); }
void qb_chdir(qbs d) { char p[4096]; dos_name(d, p, sizeof p); if (!p[0]) return; if (chdir(p) != 0) qb_error(76); }

void qb_files(qbs pattern, qb_i32 has)
{
    char dir[4096], mask[1024];
    if (!has) pattern = qb_slit("*.*", 3);
    split_pattern(pattern, dir, mask, sizeof mask);
    DIR *d = opendir(dir);
    if (!d) { qb_error(76); return; }
    char cwd[4096]; if (!getcwd(cwd, sizeof cwd)) strcpy(cwd, ".");
    qb_pr_begin(0);
    qbs line = qb_slit(cwd, strlen(cwd));
    qb_pr_s(line); qb_pr_nl();
    struct dirent *e; int n = 0;
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.' && (!e->d_name[1] || (e->d_name[1] == '.' && !e->d_name[2]))) continue;
        if (fnmatch(mask, e->d_name, FNM_CASEFOLD) != 0) continue;
        char entry[64]; char p[8192]; snprintf(p, sizeof p, "%s/%s", dir, e->d_name);
        struct stat st; int isdir = stat(p, &st) == 0 && S_ISDIR(st.st_mode);
        snprintf(entry, sizeof entry, "%-12.12s%s", e->d_name, isdir ? "<DIR> " : "      ");
        qb_pr_s(qb_slit(entry, 18));
        n++;
    }
    closedir(d);
    if (!n) { qb_pr_end(); qb_error(53); return; }
    qb_pr_nl();
    qb_pr_end();
}

void qb_lock(qb_i32 n, qb_i32 unlock) { (void)n; (void)unlock; }
qb_i32 qb_fileattr(qb_i32 n, qb_i32 attr)
{
    qbfile *q = qbf_get(n, 0);
    if (!q) return 0;
    if (attr == 1) { static const int m[] = {0, 1, 2, 8, 4, 32}; return m[q->mode]; }
    return fileno(q->f);
}
void qb_width_file(qb_i32 n, qb_i32 w) { qbfile *q = qbf_get(n, 0); if (q) q->width = w <= 0 ? 255 : w; }
qbs qb_ioctl_s(qb_i32 n) { (void)n; return qb_slit("", 0); }
void qb_ioctl(qb_i32 n, qbs s) { (void)n; (void)s; }
