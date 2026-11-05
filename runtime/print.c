/* print.c - PRINT, PRINT USING, WRITE, INPUT, LINE INPUT, INKEY$, number formatting.
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */
#include "qbrt_int.h"
#include <ctype.h>
#ifndef _WIN32
#include <unistd.h>
#endif

/* ------------------------------------------------------------------ */
/* number formatting, QB style                                        */
static void fmt_real(double v, int digits, char expch, char *out)
{
    if (v == 0 || !isfinite(v)) { strcpy(out, v == 0 || isnan(v) ? "0" : (v > 0 ? "1.701412E+38" : "-1.701412E+38")); return; }
    char buf[64];
    int neg = v < 0; if (neg) v = -v;
    snprintf(buf, sizeof buf, "%.*e", digits - 1, v);
    /* buf: d.ddddde[+-]xx */
    char mant[32]; int nm = 0; char *p = buf;
    for (; *p && *p != 'e'; p++) if (isdigit((unsigned char)*p)) mant[nm++] = *p;
    int e = atoi(p + 1);
    while (nm > 1 && mant[nm - 1] == '0') nm--;
    mant[nm] = 0;
    char *o = out;
    if (neg) *o++ = '-';
    int decimals = nm - 1 - e;  /* digits after the decimal point in fixed notation */
    if (e < digits && decimals <= digits) {
        if (e < 0) {
            *o++ = '.';
            for (int i = 0; i < -e - 1; i++) *o++ = '0';
            for (int i = 0; i < nm; i++) *o++ = mant[i];
        } else {
            for (int i = 0; i <= e; i++) *o++ = i < nm ? mant[i] : '0';
            if (nm > e + 1) { *o++ = '.'; for (int i = e + 1; i < nm; i++) *o++ = mant[i]; }
        }
        *o = 0;
    } else {
        *o++ = mant[0];
        if (nm > 1) { *o++ = '.'; for (int i = 1; i < nm; i++) *o++ = mant[i]; }
        *o++ = expch; *o++ = e < 0 ? '-' : '+';
        int ae = e < 0 ? -e : e;
        if (ae >= 100) o += sprintf(o, "%d", ae); else o += sprintf(o, "%02d", ae);
        *o = 0;
    }
}
void qb_fmt_single(float v, char *out) { fmt_real((double)v, 7, 'E', out); }
void qb_fmt_double(double v, char *out) { fmt_real(v, 16, 'D', out); }

/* parse a number like INPUT/READ/VAL would: returns 1 if ok */
int qb_parse_number(const char *s, int n, double *out, int *used)
{
    int i = 0;
    char buf[128]; int k = 0;
    if (i < n && s[i] == '&' && i + 1 < n) {
        qbs t = qb_slit(s, n); *out = qb_val(t);
        int j = i + 1; if (j < n && (s[j] == 'H' || s[j] == 'h' || s[j] == 'O' || s[j] == 'o')) j++;
        while (j < n && isxdigit((unsigned char)s[j])) j++;
        *used = j; return 1;
    }
    if (i < n && (s[i] == '+' || s[i] == '-')) buf[k++] = s[i++];
    int digits = 0;
    while (i < n && isdigit((unsigned char)s[i]) && k < 100) { buf[k++] = s[i++]; digits++; }
    if (i < n && s[i] == '.') { buf[k++] = s[i++]; while (i < n && isdigit((unsigned char)s[i]) && k < 100) { buf[k++] = s[i++]; digits++; } }
    if (!digits) { *used = i; *out = 0; return 0; }
    if (i < n && (s[i] == 'e' || s[i] == 'E' || s[i] == 'd' || s[i] == 'D')) {
        int j = i + 1; char eb[8]; int ek = 0;
        if (j < n && (s[j] == '+' || s[j] == '-')) eb[ek++] = s[j++];
        int ed = 0; while (j < n && isdigit((unsigned char)s[j]) && ek < 6) { eb[ek++] = s[j++]; ed++; }
        if (ed) { buf[k++] = 'e'; memcpy(buf + k, eb, ek); k += ek; i = j; }
        else i = j;
    }
    if (i < n && (s[i] == '!' || s[i] == '#' || s[i] == '%' || s[i] == '&')) i++;
    buf[k] = 0;
    *out = strtod(buf, NULL);
    *used = i;
    return 1;
}

/* ------------------------------------------------------------------ */
/* output channel                                                      */
static int pr_ch;       /* 0 screen, >0 file, -1 printer */
static FILE *lpt;

static void ch_write(const char *s, int n)
{
    if (n <= 0) return;
    if (pr_ch == 0) qbs_write(s, n);
    else if (pr_ch > 0) qbf_write(pr_ch, s, n);
    else {
        if (!lpt) { const char *f = getenv("QB_LPT"); lpt = f ? fopen(f, "a") : NULL; if (!lpt) lpt = stderr; }
        fwrite(s, 1, n, lpt); fflush(lpt);
    }
}
static void ch_nl(void)
{
    if (pr_ch == 0) qbs_newline();
    else if (pr_ch > 0) qbf_write(pr_ch, (qb_rt_flags & 1) ? "\r\n" : "\n", (qb_rt_flags & 1) ? 2 : 1);
    else ch_write("\n", 1);
}
static int lpt_col;
static int ch_col(void)
{
    if (pr_ch == 0) return qb_scr.ccol;
    if (pr_ch > 0) return qbf_col(pr_ch);
    return lpt_col;
}
static int ch_width(void)
{
    if (pr_ch == 0) return qbs_text_width();
    if (pr_ch > 0) return qbf_width(pr_ch);
    return 80;
}

void qb_pr_begin(qb_i32 fileno)
{
    pr_ch = fileno;
    if (fileno > 0) qbf_get(fileno, -2);
}
void qb_pr_end(void) { if (pr_ch == 0) qbd_dirty(); pr_ch = 0; }

static void pr_item(const char *s, int n)
{
    int w = ch_width();
    if (w > 0 && w < 255 && ch_col() > 0 && ch_col() + n > w) ch_nl();
    ch_write(s, n);
}
void qb_pr_s(qbs s)
{
    if (qb_errpend) return;
    if (pr_ch == 0 || pr_ch < 0) {
        /* strings wrap but are not moved to a new line as a whole when longer than a line */
        int w = ch_width();
        if (w > 0 && w < 255 && ch_col() > 0 && ch_col() + s.len > w && s.len <= w) ch_nl();
        ch_write(s.p, s.len);
    } else ch_write(s.p, s.len);
}
void qb_pr_i(qb_i32 v) { if (qb_errpend) return; char b[24]; int n = snprintf(b, sizeof b, v < 0 ? "%d " : " %d ", v); pr_item(b, n); }
void qb_pr_f(float v) { if (qb_errpend) return; char b[48]; b[0] = ' '; qb_fmt_single(v, b + 1); char *s = b[1] == '-' ? b + 1 : b; strcat(s, " "); pr_item(s, strlen(s)); }
void qb_pr_d(double v) { if (qb_errpend) return; char b[48]; b[0] = ' '; qb_fmt_double(v, b + 1); char *s = b[1] == '-' ? b + 1 : b; strcat(s, " "); pr_item(s, strlen(s)); }
void qb_pr_comma(void)
{
    if (qb_errpend) return;
    int col = ch_col(), w = ch_width();
    int next = (col / 14 + 1) * 14;
    if (pr_ch == 0 && next + 1 > w) { ch_nl(); return; }
    if (pr_ch != 0 && w < 255 && next >= w) { ch_nl(); return; }
    char sp[16]; memset(sp, ' ', 16);
    ch_write(sp, next - col);
}
void qb_pr_tab(qb_i32 n)
{
    if (qb_errpend) return;
    int w = ch_width();
    if (n < 1) n = 1;
    if (w > 0 && w < 255) n = (n - 1) % w + 1;
    int col = ch_col();
    if (col > n - 1) { ch_nl(); col = 0; }
    while (col < n - 1) { ch_write(" ", 1); col++; }
}
void qb_pr_spc(qb_i32 n)
{
    if (qb_errpend) return;
    int w = ch_width();
    if (n < 0) n = 0;
    if (w > 0 && w < 255) n %= w;
    for (int i = 0; i < n; i++) {
        if (pr_ch == 0 && ch_col() >= w) ch_nl();
        ch_write(" ", 1);
    }
}
void qb_pr_nl(void) { if (qb_errpend) return; ch_nl(); }

/* ------------------------------------------------------------------ */
/* PRINT USING                                                         */
static qbs pu_fmt;
static int pu_pos;
static int pu_used_field;

static void pu_literal_until_field(int stop_at_end);

void qb_pu_begin(qbs fmt)
{
    pu_fmt = qb_scopy(fmt);
    pu_pos = 0; pu_used_field = 0;
    pu_literal_until_field(1);
}

static int is_numfield_start(const char *f, int n, int i)
{
    char c = f[i];
    if (c == '#') return 1;
    if (c == '.' && i + 1 < n && f[i + 1] == '#') return 1;
    if (c == '+' && i + 1 < n && (f[i + 1] == '#' || (f[i + 1] == '.' && i + 2 < n && f[i + 2] == '#') || (i + 2 < n && f[i + 1] == '$' && f[i + 2] == '$') || (i + 2 < n && f[i + 1] == '*' && f[i + 2] == '*'))) return 1;
    if (c == '$' && i + 1 < n && f[i + 1] == '$') return 1;
    if (c == '*' && i + 1 < n && f[i + 1] == '*') return 1;
    return 0;
}
static int is_strfield_start(const char *f, int n, int i)
{
    char c = f[i];
    if (c == '!' || c == '&') return 1;
    if (c == '\\') { int j = i + 1; while (j < n && f[j] == ' ') j++; return j < n && f[j] == '\\'; }
    return 0;
}

/* emit literal characters up to the next field; at end of format wrap if requested */
static void pu_literal_until_field(int at_begin)
{
    const char *f = pu_fmt.p; int n = pu_fmt.len;
    (void)at_begin;
    while (pu_pos < n) {
        if (f[pu_pos] == '_' && pu_pos + 1 < n) { ch_write(f + pu_pos + 1, 1); pu_pos += 2; continue; }
        if (is_numfield_start(f, n, pu_pos) || is_strfield_start(f, n, pu_pos)) return;
        ch_write(f + pu_pos, 1); pu_pos++;
    }
}

static int pu_next_field(void)
{
    if (pu_pos >= pu_fmt.len) {
        if (!pu_used_field) { qb_error(5); return 0; }
        pu_pos = 0;
        pu_literal_until_field(0);
        if (pu_pos >= pu_fmt.len) { qb_error(5); return 0; }
    }
    return 1;
}

void qb_pu_s(qbs s)
{
    if (qb_errpend) return;
    if (!pu_next_field()) return;
    const char *f = pu_fmt.p; int n = pu_fmt.len;
    if (!is_strfield_start(f, n, pu_pos)) { qb_error(13); return; }
    pu_used_field = 1;
    char c = f[pu_pos];
    if (c == '!') { ch_write(s.len ? s.p : " ", 1); pu_pos++; }
    else if (c == '&') { ch_write(s.p, s.len); pu_pos++; }
    else {
        int j = pu_pos + 1; while (f[j] != '\\') j++;
        int w = j - pu_pos + 1;
        int k = s.len < w ? s.len : w;
        ch_write(s.p, k);
        for (int i = k; i < w; i++) ch_write(" ", 1);
        pu_pos = j + 1;
    }
    pu_literal_until_field(0);
}

static void insert_commas(char *digits)
{
    char tmp[512]; int n = strlen(digits), o = 0;
    for (int i = 0; i < n; i++) {
        tmp[o++] = digits[i];
        int rem = n - 1 - i;
        if (rem > 0 && rem % 3 == 0) tmp[o++] = ',';
    }
    tmp[o] = 0; strcpy(digits, tmp);
}

void qb_pu_d(double v, qb_i32 isdbl)
{
    if (qb_errpend) return;
    if (!pu_next_field()) return;
    const char *f = pu_fmt.p; int n = pu_fmt.len;
    if (!is_numfield_start(f, n, pu_pos)) { qb_error(13); return; }
    pu_used_field = 1;
    int i = pu_pos;
    int lead_plus = 0, dollar = 0, stars = 0, commas = 0, before = 0, after = -1, expn = 0, trail = 0;
    if (f[i] == '+') { lead_plus = 1; i++; }
    if (i + 2 < n && f[i] == '*' && f[i + 1] == '*' && f[i + 2] == '$') { stars = 1; dollar = 1; before += 2; i += 3; }
    else if (i + 1 < n && f[i] == '*' && f[i + 1] == '*') { stars = 1; before += 2; i += 2; }
    else if (i + 1 < n && f[i] == '$' && f[i + 1] == '$') { dollar = 1; before += 1; i += 2; }
    while (i < n && (f[i] == '#' || f[i] == ',')) { if (f[i] == ',') commas = 1; before++; i++; }
    if (i < n && f[i] == '.') { after = 0; i++; while (i < n && f[i] == '#') { after++; i++; } }
    if (i + 3 < n && f[i] == '^' && f[i + 1] == '^' && f[i + 2] == '^' && f[i + 3] == '^') {
        expn = 4; i += 4; if (i < n && f[i] == '^') { expn = 5; i++; }
    }
    if (!lead_plus && i < n && (f[i] == '+' || f[i] == '-')) { trail = f[i]; i++; }
    pu_pos = i;
    int decs = after < 0 ? 0 : after;
    char out[600]; int o = 0;
    int neg = v < 0; double a = fabs(v);
    char sign = 0;
    if (lead_plus || trail == '+') sign = neg ? '-' : '+';
    else if (trail == '-') sign = neg ? '-' : ' ';
    else if (neg) sign = '-';
    if (expn) {
        /* scientific: before digits (one reserved for sign if no sign spec) */
        int intd = before;
        if (!lead_plus && !trail && intd > 0) intd--;   /* room for sign */
        if (intd < 0) intd = 0;
        int sig = intd + decs; if (sig < 1) sig = 1;
        int e = 0;
        if (a != 0) {
            e = (int)floor(log10(a)) - (intd > 0 ? intd - 1 : -1);
            double m = a / pow(10, e);
            char t[64]; snprintf(t, sizeof t, "%.*f", decs, m);
            if (strlen(t) > (size_t)(intd + (decs ? decs + 1 : 0)) && intd > 0) { e++; m = a / pow(10, e); }
        }
        double m = a == 0 ? 0 : a / pow(10, e);
        char num[128]; snprintf(num, sizeof num, "%.*f", decs, m);
        if (intd == 0 && num[0] == '0') memmove(num, num + 1, strlen(num));
        char body[200]; int bl = 0;
        if (sign && !trail) body[bl++] = sign;
        else if (!lead_plus && !trail && before > 0 && !neg) body[bl++] = ' ';
        bl += sprintf(body + bl, "%s", num);
        if (after == 0) body[bl++] = '.';
        int ae = e < 0 ? -e : e;
        bl += sprintf(body + bl, expn == 5 ? "E%c%03d" : "E%c%02d", e < 0 ? '-' : '+', ae);
        if (trail) body[bl++] = sign;
        body[bl] = 0;
        memcpy(out, body, bl); o = bl;
        ch_write(out, o);
        pu_literal_until_field(0);
        return;
    }
    char num[512];
    /* QB rounds halves away from zero on the decimal representation of the value */
    {
        char t[600];
        int sig = isdbl ? 16 : 7;
        double r = a;
        if (r != 0) {
            snprintf(t, sizeof t, "%.*e", sig - 1, r);       /* significant digits of the value */
            r = strtod(t, NULL);
        }
        double p10 = pow(10.0, decs);
        double sc = r * p10;
        double fl = floor(sc);
        double frac = sc - fl;
        if (frac >= 0.5) fl += 1;
        if (decs <= 15 && fabs(sc) < 9e15) snprintf(num, sizeof num, "%.*f", decs, fl / p10);
        else snprintf(num, sizeof num, "%.*f", decs, r);
    }
    char *dot = strchr(num, '.');
    char ip[512], fp[128] = "";
    if (dot) { *dot = 0; strcpy(fp, dot + 1); }
    strcpy(ip, num);
    if (strcmp(ip, "0") == 0 && before > 0) {
        /* keep a leading zero only if there is room */
    }
    if (commas) insert_commas(ip);
    int width = before + (lead_plus ? 1 : 0);
    char field[600]; int fl = 0;
    /* compose integer part with sign/dollar */
    char left[600]; int ll = 0;
    if (sign && !trail && !(lead_plus) ) left[ll++] = sign;
    if (lead_plus) left[ll++] = sign;
    if (dollar) left[ll++] = '$';
    int ipl = strlen(ip);
    if (strcmp(ip, "0") == 0 && after > 0 && before - (dollar ? 1 : 0) - (stars ? 0 : 0) <= (sign && !trail && !lead_plus ? 1 : 0)) ipl = 0;
    memcpy(left + ll, ip, ipl); ll += ipl;
    int total_left = width + (dollar && !stars ? 1 : 0) + (stars && dollar ? 1 : 0);
    total_left = before + (lead_plus ? 1 : 0) + (dollar ? 1 : 0);
    if (stars && dollar) total_left = before + 1 + (lead_plus ? 1 : 0);
    int overflow = ll > total_left;
    if (overflow) field[fl++] = '%';
    int pad = total_left - ll;
    for (int k = 0; k < pad; k++) field[fl++] = stars ? '*' : ' ';
    memcpy(field + fl, left, ll); fl += ll;
    if (after >= 0) { field[fl++] = '.'; memcpy(field + fl, fp, strlen(fp)); fl += strlen(fp); }
    if (trail) field[fl++] = sign;
    ch_write(field, fl);
    pu_literal_until_field(0);
}

void qb_pu_end(qb_i32 newline)
{
    if (newline) ch_nl();
    if (pr_ch == 0) qbd_dirty();
    pr_ch = 0;
}

/* ------------------------------------------------------------------ */
/* WRITE                                                               */
static int wr_count;
static void wr_sep(void) { if (wr_count++) ch_write(",", 1); }
void qb_wr_s(qbs s) { wr_sep(); ch_write("\"", 1); ch_write(s.p, s.len); ch_write("\"", 1); }
void qb_wr_i(qb_i32 v) { wr_sep(); char b[24]; int n = snprintf(b, sizeof b, "%d", v); ch_write(b, n); }
void qb_wr_f(float v) { wr_sep(); char b[48]; qb_fmt_single(v, b); ch_write(b, strlen(b)); }
void qb_wr_d(double v) { wr_sep(); char b[48]; qb_fmt_double(v, b); ch_write(b, strlen(b)); }
void qb_wr_end(void) { ch_nl(); wr_count = 0; if (pr_ch == 0) qbd_dirty(); pr_ch = 0; }

/* ------------------------------------------------------------------ */
/* keyboard                                                            */
static int pend_byte = -1;
static int inkey_idle;

qbs qb_inkey(void)
{
    int k = qbd_getkey(0);
    if (k < 0) {
        if (++inkey_idle > 64) { qb_msleep(1); inkey_idle = 32; }
        return qb_slit("", 0);
    }
    inkey_idle = 0;
    if (k & 0x100) { qbs r = qb_stmp(2); r.p[0] = 0; r.p[1] = (char)(k & 0xFF); return r; }
    qbs r = qb_stmp(1); r.p[0] = (char)k; return r;
}

static int wait_key_byte(void)
{
    if (pend_byte >= 0) { int b = pend_byte; pend_byte = -1; return b; }
    qbd_flush();
    for (;;) {
        int k = qbd_getkey(100);
        if (k >= 0) {
            if (k & 0x100) { pend_byte = k & 0xFF; return 0; }
            return k;
        }
        if (qb_mode_display == QBD_HEADLESS) { qbd_shutdown(0); _exit(0); }
        if (qb_mode_display == QBD_STREAM && !qb_line_tty) {
            int c = getchar();
            if (c == EOF) { qb_end(); }
            return c == '\n' ? 13 : c;
        }
    }
}

qbs qb_input_n(qb_i32 n, qb_i32 fileno)
{
    if (n < 0 || n > 32767) { qb_error(5); return qb_slit("", 0); }
    qbs r = qb_stmp(n);
    if (fileno == QB_NA || fileno == 0) {
        qb_scr.input_cursor = 1;
        for (int i = 0; i < n; i++) r.p[i] = (char)wait_key_byte();
        qb_scr.input_cursor = 0;
        return r;
    }
    if (!qbf_get(fileno, -3)) return qb_slit("", 0);
    for (int i = 0; i < n; i++) {
        int c = qbf_getc(fileno);
        if (c < 0) { qb_error(62); r.len = i; return r; }
        r.p[i] = (char)c;
    }
    return r;
}

/* line editor used by INPUT and LINE INPUT on the screen */
static qbs read_line_screen(void)
{
    if (qb_mode_display == QBD_STREAM) {
        qbd_line_cooked();
        fflush(stdout);
        char buf[4096];
        if (!fgets(buf, sizeof buf, stdin)) { qb_end(); }
        int n = strlen(buf); while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r')) n--;
        /* echo so that redirected output still looks like a session */
        qbs r = qb_stmp(n); memcpy(r.p, buf, n);
        qb_scr.ccol = 0;
        return r;
    }
    char buf[256]; int n = 0;
    int startrow = qb_scr.crow, startcol = qb_scr.ccol;
    (void)startrow; (void)startcol;
    qb_scr.input_cursor = 1;
    qbs_cursor_blink_reset();
    qbd_flush();
    for (;;) {
        int k = qbd_getkey(100);
        if (k < 0) {
            if (qb_mode_display == QBD_HEADLESS) { qb_scr.input_cursor = 0; qbd_shutdown(0); _exit(0); }
            continue;
        }
        if (k == 13) break;
        if (k == 8 || k == (0x100 | 75)) {
            if (n > 0) {
                n--;
                if (qb_scr.ccol > 0) qb_scr.ccol--;
                else if (qb_scr.crow > qb_scr.vtop) { qb_scr.crow--; qb_scr.ccol = qb_scr.cols - 1; }
                qbs_set_text_cell(qb_scr.crow, qb_scr.ccol, ' ', -1);
                qbd_dirty();
            }
            continue;
        }
        if (k == 27) {
            while (n > 0) { n--; if (qb_scr.ccol > 0) qb_scr.ccol--; else if (qb_scr.crow > qb_scr.vtop) { qb_scr.crow--; qb_scr.ccol = qb_scr.cols - 1; } qbs_set_text_cell(qb_scr.crow, qb_scr.ccol, ' ', -1); }
            qbd_dirty();
            continue;
        }
        if (k & 0x100) continue;
        if (k < 32 && k != 9) continue;
        if (n < 255) { buf[n++] = (char)k; char c = (char)k; qbs_write(&c, 1); qbd_dirty(); }
    }
    qb_scr.input_cursor = 0;
    qbs r = qb_stmp(n); memcpy(r.p, buf, n);
    return r;
}

/* ------------------------------------------------------------------ */
/* INPUT                                                               */
static int in_ch;            /* channel */
static qbs in_fields[64];
static int in_nf, in_idx;

static int field_ok(qbs f, char t)
{
    if (t == 's') return 1;
    int i = 0; while (i < f.len && f.p[i] == ' ') i++;
    int j = f.len; while (j > i && f.p[j - 1] == ' ') j--;
    if (i == j) return 1;  /* empty is 0 */
    double v; int used;
    if (!qb_parse_number(f.p + i, j - i, &v, &used)) return 0;
    if (used != j - i) return 0;
    if (t == 'i' && (v < -32768.5 || v > 32767.5)) return 2;
    if (t == 'l' && (v < -2147483648.5 || v > 2147483647.5)) return 2;
    return 1;
}

static int split_fields(qbs line, int want)
{
    in_nf = 0;
    int i = 0, n = line.len;
    for (;;) {
        while (i < n && line.p[i] == ' ') i++;
        int start, end;
        if (i < n && line.p[i] == '"') {
            start = ++i; while (i < n && line.p[i] != '"') i++;
            end = i; if (i < n) i++;
            while (i < n && line.p[i] == ' ') i++;
            if (i < n && line.p[i] != ',') { /* garbage after quote */ }
            while (i < n && line.p[i] != ',') i++;
        } else {
            start = i; while (i < n && line.p[i] != ',') i++;
            end = i; while (end > start && line.p[end - 1] == ' ') end--;
        }
        if (in_nf < 64) { qbs f = qb_stmp(end - start); memcpy(f.p, line.p + start, end - start); in_fields[in_nf++] = f; }
        if (i < n && line.p[i] == ',') { i++; continue; }
        break;
    }
    (void)want;
    return in_nf;
}

void qb_in_begin(qb_i32 fileno, qbs prompt, qb_i32 flags, const char *types)
{
    in_ch = fileno; in_idx = 0; in_nf = 0;
    if (fileno > 0) { qbf_get(fileno, 1); return; }
    int want = strlen(types);
    for (;;) {
        qb_pr_begin(0);
        if (prompt.len) qb_pr_s(prompt);
        if (!(flags & 2)) qb_pr_s(qb_slit("? ", 2));
        qbd_dirty();
        qbs line = read_line_screen();
        if (qb_mode_display == QBD_STREAM && !qb_line_tty) {
            /* echo input so transcripts look like the DOS screen (a terminal echoes by itself) */
            fwrite(line.p, 1, line.len, stdout);
        }
        int nf = split_fields(line, want);
        int ok = nf == want;
        if (nf == 1 && want == 1) ok = 1;
        for (int i = 0; ok && i < want && i < nf; i++) {
            int r = field_ok(in_fields[i], types[i]);
            if (r != 1) ok = 0;
            if (r == 2) { qbs_newline(); qbs_write("Overflow", 8); }
        }
        if (ok) { if (!(flags & 1) && !qb_line_tty) qbs_newline(); break; }
        if (!qb_line_tty) qbs_newline();
        qbs_write("Redo from start", 15);
        qbs_newline();
    }
    qbd_dirty();
}

/* ---- file item reading ---- */
static int file_skip_ws(int fn, int newlines)
{
    for (;;) {
        int c = qbf_getc(fn);
        if (c < 0) return -1;
        if (c == ' ' || c == '\t' || (newlines && (c == '\r' || c == '\n'))) continue;
        return c;
    }
}
void qbf_ungetc(int n, int c);

static qbs file_read_item(int fn, int numeric)
{
    char buf[32768]; int n = 0;
    int c = file_skip_ws(fn, 1);
    if (c < 0) { qb_error(62); return qb_slit("", 0); }
    if (c == 0x1A) { qb_error(62); return qb_slit("", 0); }
    if (!numeric && c == '"') {
        while ((c = qbf_getc(fn)) >= 0 && c != '"' && n < 32767) buf[n++] = (char)c;
        /* skip to delimiter */
        while ((c = qbf_getc(fn)) >= 0 && c != ',' && c != '\n' && c != '\r') ;
        if (c == '\r') { int d = qbf_getc(fn); if (d != '\n' && d >= 0) qbf_ungetc(fn, d); }
    } else {
        buf[n++] = (char)c;
        while ((c = qbf_getc(fn)) >= 0 && c != ',' && c != '\n' && c != '\r' && n < 32767) {
            if (numeric && (c == ' ' || c == '\t')) { /* number ends at blank */
                int d; while ((d = qbf_getc(fn)) == ' ' || d == '\t') ;
                if (d >= 0 && d != ',' && d != '\r' && d != '\n') qbf_ungetc(fn, d);
                c = d; break;
            }
            buf[n++] = (char)c;
        }
        if (c == '\r') { int d = qbf_getc(fn); if (d != '\n' && d >= 0) qbf_ungetc(fn, d); }
        if (!numeric) while (n > 0 && buf[n - 1] == ' ') n--;
    }
    qbs r = qb_stmp(n); memcpy(r.p, buf, n); return r;
}

static qbs next_field(int numeric)
{
    if (in_ch > 0) return file_read_item(in_ch, numeric);
    if (in_idx < in_nf) return in_fields[in_idx++];
    return qb_slit("", 0);
}
static double field_num(qbs f)
{
    int i = 0; while (i < f.len && f.p[i] == ' ') i++;
    double v = 0; int used;
    qb_parse_number(f.p + i, f.len - i, &v, &used);
    return v;
}
void qb_in_i16(qb_i16 *v) { *v = qb_cint(field_num(next_field(1))); }
void qb_in_i32(qb_i32 *v) { *v = qb_clng(field_num(next_field(1))); }
void qb_in_f(float *v) { *v = (float)field_num(next_field(1)); }
void qb_in_d(double *v) { *v = field_num(next_field(1)); }
void qb_in_s(qbs *v) { qb_sset(v, next_field(0)); }
void qb_in_fs(char *buf, qb_i32 n) { qb_fsset(buf, n, next_field(0)); }
void qb_in_end(void) { in_ch = 0; in_nf = 0; qbd_dirty(); }

static qbs file_line(int fn)
{
    static char *buf; static int cap;
    int n = 0;
    int c = qbf_getc(fn);
    if (c < 0 || c == 0x1A) { qb_error(62); return qb_slit("", 0); }
    while (c >= 0 && c != '\n' && c != '\r') {
        if (n + 1 >= cap) { cap = cap ? cap * 2 : 4096; buf = realloc(buf, cap); }
        buf[n++] = (char)c;
        c = qbf_getc(fn);
    }
    if (c == '\r') { int d = qbf_getc(fn); if (d != '\n' && d >= 0) qbf_ungetc(fn, d); }
    qbs r = qb_stmp(n); if (n) memcpy(r.p, buf, n); return r;
}

void qb_lineinput(qb_i32 fileno, qbs prompt, qb_i32 flags, qbs *dst)
{
    if (fileno > 0) { if (!qbf_get(fileno, 1)) return; qb_sset(dst, file_line(fileno)); return; }
    qb_pr_begin(0);
    if (prompt.len) qb_pr_s(prompt);
    qbd_dirty();
    qbs line = read_line_screen();
    if (qb_mode_display == QBD_STREAM && !qb_line_tty) fwrite(line.p, 1, line.len, stdout);
    if (!(flags & 1) && !qb_line_tty) qbs_newline();
    qb_sset(dst, line);
    qbd_dirty();
}
void qb_lineinput_fs(qb_i32 fileno, qbs prompt, qb_i32 flags, char *buf, qb_i32 n)
{
    qbs t = {0, 0, 0};
    qb_lineinput(fileno, prompt, flags, &t);
    qb_fsset(buf, n, t);
    qb_sfree(&t);
}
