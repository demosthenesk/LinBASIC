/* mem.c - emulated PC memory, I/O ports and software interrupts:
 * DEF SEG/PEEK/POKE, INP/OUT/WAIT, BLOAD/BSAVE, CALL INTERRUPT.
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */
#include "qbrt_int.h"
#ifndef _WIN32
#include <unistd.h>
#endif
#include <time.h>

static unsigned char *ram;        /* 1 MB conventional + upper memory */
static int defseg = -1;           /* -1 = BASIC data segment          */
#define DGROUP 0x1000

void qbm_init(void)
{
    ram = calloc(1, 0x110000);
    /* BIOS data area */
    ram[0x449] = 3;                      /* video mode   */
    ram[0x44A] = 80;                     /* columns      */
    ram[0x484] = 24;                     /* rows - 1     */
    ram[0x410] = 0x21;
    ram[0x463] = 0xD4; ram[0x464] = 0x03;
}

void qb_defseg(qb_i32 seg) { defseg = seg == QB_NA ? -1 : (seg & 0xFFFF); }

static long linear(qb_i32 addr)
{
    long seg = defseg < 0 ? DGROUP : defseg;
    if (addr < -65536 || addr > 65535) { qb_error(5); return -1; }
    return ((seg << 4) + (addr & 0xFFFF)) & 0xFFFFF;
}

static unsigned ticks(void)
{
    struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
    struct tm tm; localtime_r(&ts.tv_sec, &tm);
    double s = tm.tm_hour * 3600 + tm.tm_min * 60 + tm.tm_sec + ts.tv_nsec / 1e9;
    return (unsigned)(s * 18.2065);
}

static int mem_read(long a)
{
    qbscreen *s = &qb_scr;
    if (a >= 0xB8000 && a < 0xC0000 && s->text) {
        long o = a - 0xB8000;
        int pagesize = s->cols * 2 * 25 > 4096 ? 8192 : (s->cols == 40 ? 2048 : 4096);
        if (s->rows > 25) pagesize = s->cols * s->rows * 2;
        int page = o / pagesize; o %= pagesize;
        if (page < s->npages && o / 2 < s->cols * s->rows) {
            uint16_t v = s->txt[page][o / 2];
            return (o & 1) ? (v >> 8) : (v & 0xFF);
        }
        return 0;
    }
    if (a >= 0xA0000 && a < 0xB0000 && s->mode == 13) {
        long o = a - 0xA0000;
        if (o < s->w * s->h) return s->pix[0][o];
        return 0;
    }
    if (a == 0x417) return qbd_shift_state() & 0xFF;
    if (a >= 0x46C && a <= 0x46F) { unsigned t = ticks(); return (t >> (8 * (a - 0x46C))) & 0xFF; }
    if (a == 0x450) return qb_scr.ccol;
    if (a == 0x451) return qb_scr.crow;
    if (a == 0x449) { static const int bios[] = { 3, 4, 6, 7, 0x40, 0, 0, 0xD, 0xE, 0x10, 0xF, 0x11, 0x12, 0x13 }; int m = qb_scr.mode; return m <= 13 ? bios[m] : 3; }
    return ram[a];
}

static void mem_write(long a, int v)
{
    qbscreen *s = &qb_scr;
    v &= 0xFF;
    if (a >= 0xB8000 && a < 0xC0000 && s->text) {
        qbd_need_screen();
        long o = a - 0xB8000;
        int pagesize = s->cols == 40 ? 2048 : 4096;
        if (s->rows > 25) pagesize = s->cols * s->rows * 2;
        int page = o / pagesize; o %= pagesize;
        if (page < s->npages && o / 2 < s->cols * s->rows) {
            uint16_t *c = &s->txt[page][o / 2];
            *c = (o & 1) ? (uint16_t)((*c & 0xFF) | (v << 8)) : (uint16_t)((*c & 0xFF00) | v);
            s->dirty = 1;
        }
        return;
    }
    if (a >= 0xA0000 && a < 0xB0000 && s->mode == 13) {
        long o = a - 0xA0000;
        if (o < s->w * s->h) { s->pix[0][o] = (unsigned char)v; s->dirty = 1; }
        return;
    }
    ram[a] = (unsigned char)v;
}

qb_i32 qb_peek(qb_i32 addr) { long a = linear(addr); return a < 0 ? 0 : mem_read(a); }
void qb_poke(qb_i32 addr, qb_i32 v) { long a = linear(addr); if (a >= 0) mem_write(a, v); }

/* ---- ports ------------------------------------------------------------- */
static int dac_windex, dac_rindex, dac_comp;
static int dac_tmp[3];
static int pit_latch, pit_lo, pit_state, port61;
static int last_scan;

qb_i32 qb_inp(qb_i32 port)
{
    if (port < 0 || port > 65535) { qb_error(5); return 0; }
    switch (port) {
    case 0x3DA: case 0x3BA: {
        /* bit 3: vertical retrace (about 1.2 ms out of each 70 Hz frame), bit 0: display disabled */
        double t = qb_now() * 70.0; double f = t - floor(t);
        int v = 0; if (f > 0.92) v |= 8 | 1; else if (fmod(t * 449, 1.0) > 0.8) v |= 1;
        return v;
    }
    case 0x3C9: {
        uint32_t c = qb_scr.pal[dac_rindex & 255];
        int comp = dac_comp % 3; int val = comp == 0 ? (c >> 16) & 255 : comp == 1 ? (c >> 8) & 255 : c & 255;
        if (++dac_comp % 3 == 0) dac_rindex++;
        return val * 63 / 255;
    }
    case 0x3C8: return dac_windex;
    case 0x60: return last_scan;
    case 0x61: return port61;
    case 0x201: return 0xF0;
    }
    return 0xFF;
}

void qb_out(qb_i32 port, qb_i32 v)
{
    if (port < 0 || port > 65535) { qb_error(5); return; }
    v &= 0xFF;
    switch (port) {
    case 0x3C8: dac_windex = v; dac_comp = 0; break;
    case 0x3C7: dac_rindex = v; dac_comp = 0; break;
    case 0x3C9:
        dac_tmp[dac_comp % 3] = v & 63;
        if (++dac_comp % 3 == 0) {
            int i = dac_windex & 255;
            qb_scr.pal[i] = ((uint32_t)(dac_tmp[0] * 255 / 63) << 16) | ((uint32_t)(dac_tmp[1] * 255 / 63) << 8) | (uint32_t)(dac_tmp[2] * 255 / 63);
            dac_windex++;
            qb_scr.dirty = 1;
        }
        break;
    case 0x43: pit_state = 0; break;
    case 0x42:
        if (pit_state == 0) { pit_lo = v; pit_state = 1; }
        else { pit_latch = pit_lo | (v << 8); pit_state = 0; if ((port61 & 3) == 3 && pit_latch) qbsnd_speaker(1, 1193180.0 / pit_latch); }
        break;
    case 0x61:
        port61 = v;
        if ((v & 3) == 3 && pit_latch) qbsnd_speaker(1, 1193180.0 / pit_latch); else qbsnd_speaker(0, 0);
        break;
    }
}

void qb_wait(qb_i32 port, qb_i32 andv, qb_i32 xorv)
{
    if (xorv == QB_NA) xorv = 0;
    qbd_flush();
    if (port == 0x3DA || port == 0x3BA) {
        /* wait for (or out of) vertical retrace using the 70 Hz virtual clock */
        double t = qb_now() * 70.0; double f = t - floor(t);
        int inret = f > 0.92;
        int want = ((((inret ? 9 : 0) ^ xorv) & andv) != 0);
        if (want) return;
        double target;
        if ((andv & 8) && !(xorv & 8)) target = (floor(t) + (f > 0.92 ? 1 : 0) + 0.921) / 70.0;   /* until retrace starts */
        else target = (floor(t) + 1.0) / 70.0;                                                    /* until retrace ends   */
        double d = target - qb_now();
        if (d > 0) { struct timespec ts = { 0, (long)(d * 1e9) }; nanosleep(&ts, NULL); }
        return;
    }
    for (int i = 0; i < 2000; i++) {
        if (((qb_inp(port) ^ xorv) & andv) != 0) return;
        qb_msleep(1);
    }
}

/* ---- BLOAD / BSAVE ------------------------------------------------------- */
void qb_bsave(qbs name, qb_i32 off, qb_i32 len)
{
    char path[4096]; char *c = qb_cstr(name); qb_path_from_dos(c, path, sizeof path);
    FILE *f = fopen(path, "wb");
    if (!f) { qb_error(75); return; }
    long seg = defseg < 0 ? DGROUP : defseg;
    unsigned char hdr[7] = { 0xFD, seg & 0xFF, (seg >> 8) & 0xFF, off & 0xFF, (off >> 8) & 0xFF, len & 0xFF, (len >> 8) & 0xFF };
    fwrite(hdr, 1, 7, f);
    for (long i = 0; i < (len & 0xFFFF); i++) { long a = ((seg << 4) + ((off + i) & 0xFFFF)) & 0xFFFFF; fputc(mem_read(a), f); }
    fputc(0x1A, f);
    fclose(f);
}

void qb_bload(qbs name, qb_i32 off, qb_i32 has_off)
{
    char res[4096]; char path[4096]; char *c = qb_cstr(name); qb_path_from_dos(c, path, sizeof path);
    FILE *f = qb_fopen_ci(path, "rb", res, sizeof res);
    if (!f) { qb_error(53); return; }
    unsigned char hdr[7];
    if (fread(hdr, 1, 7, f) != 7 || hdr[0] != 0xFD) { fclose(f); qb_error(54); return; }
    long seg = hdr[1] | (hdr[2] << 8), o = hdr[3] | (hdr[4] << 8), len = hdr[5] | (hdr[6] << 8);
    if (has_off) { seg = defseg < 0 ? DGROUP : defseg; o = off & 0xFFFF; }
    for (long i = 0; i < len; i++) { int ch = fgetc(f); if (ch == EOF) break; mem_write(((seg << 4) + ((o + i) & 0xFFFF)) & 0xFFFFF, ch); }
    fclose(f);
}

/* ---- CALL INTERRUPT ----------------------------------------------------- */
typedef struct { qb_i16 ax, bx, cx, dx, bp, si, di, flags, ds, es; } regs;
extern int qb_mouse_x, qb_mouse_y, qb_mouse_b, qb_mouse_shown;
int qb_mouse_x, qb_mouse_y, qb_mouse_b, qb_mouse_shown;

void qb_interrupt(qb_i32 intno, void *in, void *out, qb_i32 x)
{
    regs r; memset(&r, 0, sizeof r);
    memcpy(&r, in, x ? sizeof(regs) : 8 * sizeof(qb_i16));
    int ah = (r.ax >> 8) & 0xFF, al = r.ax & 0xFF;
    switch (intno & 0xFF) {
    case 0x33:   /* mouse */
        switch (r.ax) {
        case 0: r.ax = -1; r.bx = 2; break;
        case 1: qb_mouse_shown = 1; break;
        case 2: qb_mouse_shown = 0; break;
        case 3: r.bx = qb_mouse_b; r.cx = qb_mouse_x; r.dx = qb_mouse_y; break;
        case 4: qb_mouse_x = r.cx; qb_mouse_y = r.dx; break;
        default: break;
        }
        break;
    case 0x10:   /* video BIOS */
        switch (ah) {
        case 0x00: { static const int m[] = { 0x03, 0, 0x04, 1, 0x06, 2, 0x0D, 7, 0x0E, 8, 0x10, 9, 0x11, 11, 0x12, 12, 0x13, 13 };
                     int mode = 0; for (int i = 0; i < 18; i += 2) if (m[i] == (al & 0x7F)) mode = m[i + 1];
                     qb_screen(mode, QB_NA, QB_NA, QB_NA); break; }
        case 0x01: qb_scr.cursor_on = !((r.cx >> 8) & 0x20); break;
        case 0x02: qb_scr.crow = (r.dx >> 8) & 0xFF; qb_scr.ccol = r.dx & 0xFF; break;
        case 0x03: r.dx = (qb_i16)((qb_scr.crow << 8) | qb_scr.ccol); r.cx = 0x0607; break;
        case 0x09: case 0x0A: for (int i = 0; i < (r.cx ? r.cx : 1); i++) qbs_set_text_cell(qb_scr.crow, qb_scr.ccol + i, al, ah == 9 ? (r.bx & 0xFF) : -1); break;
        case 0x0C: if (!qb_scr.text) qb_pset(0, r.cx, r.dx, al, 0); break;
        case 0x0D: r.ax = (qb_i16)((r.ax & 0xFF00) | (qb_scr.text ? 0 : (qb_point(r.cx, r.dx) & 0xFF))); break;
        case 0x0E: { char c = (char)al; qbs_write(&c, 1); break; }
        case 0x0F: r.ax = (qb_i16)((qb_scr.cols << 8) | qb_peek(0)); { int save = defseg; defseg = 0; r.ax = (qb_i16)((qb_scr.cols << 8) | mem_read(0x449)); defseg = save; } break;
        case 0x10: if (al == 0x10) { int i = r.bx & 255; qb_scr.pal[i] = ((uint32_t)(((r.dx >> 8) & 63) * 255 / 63) << 16) | ((uint32_t)(((r.cx >> 8) & 63) * 255 / 63) << 8) | (uint32_t)((r.cx & 63) * 255 / 63); qb_scr.dirty = 1; } break;
        }
        break;
    case 0x16:   /* keyboard */
        if (ah == 0 || ah == 0x10) { int k; while ((k = qbd_getkey(100)) < 0) { if (qb_mode_display == QBD_HEADLESS) { qbd_shutdown(0); _exit(0); } } r.ax = (k & 0x100) ? (qb_i16)((k & 0xFF) << 8) : (qb_i16)k; }
        else if (ah == 1 || ah == 0x11) { int k = qbd_getkey(0); if (k >= 0) { qbd_key_push(k); r.flags &= ~0x40; r.ax = (k & 0x100) ? (qb_i16)((k & 0xFF) << 8) : (qb_i16)k; } else r.flags |= 0x40; }
        else if (ah == 2) r.ax = (qb_i16)((r.ax & 0xFF00) | (qbd_shift_state() & 0xFF));
        break;
    case 0x1A:
        if (ah == 0) { unsigned t = ticks(); r.cx = (qb_i16)(t >> 16); r.dx = (qb_i16)(t & 0xFFFF); r.ax &= 0xFF00; }
        break;
    case 0x21: {
        time_t t = time(NULL); struct tm tm; localtime_r(&t, &tm);
        switch (ah) {
        case 0x2A: r.cx = (qb_i16)(tm.tm_year + 1900); r.dx = (qb_i16)(((tm.tm_mon + 1) << 8) | tm.tm_mday); r.ax = (qb_i16)((r.ax & 0xFF00) | tm.tm_wday); break;
        case 0x2C: r.cx = (qb_i16)((tm.tm_hour << 8) | tm.tm_min); r.dx = (qb_i16)(tm.tm_sec << 8); break;
        case 0x30: r.ax = 0x0005; r.bx = 0; break;
        case 0x19: r.ax = (qb_i16)((r.ax & 0xFF00) | 2); break;
        case 0x0E: r.ax = (qb_i16)((r.ax & 0xFF00) | 26); break;
        case 0x02: { char c = (char)(r.dx & 0xFF); qbs_write(&c, 1); break; }
        default: r.flags |= 1; break;
        }
        break;
    }
    default: break;
    }
    memcpy(out, &r, x ? sizeof(regs) : 8 * sizeof(qb_i16));
}

void qb_absolute(void) { qb_error(5); }
qb_i32 qb_varptr(void *p) { return (qb_i32)((uintptr_t)p & 0xFFFF); }
qb_i32 qb_varseg(void *p) { (void)p; return DGROUP; }
qb_i32 qb_saddr(qbs s) { return (qb_i32)((uintptr_t)s.p & 0xFFFF); }
qb_i32 qb_stick(qb_i32 n) { (void)n; return 0; }
qb_i32 qb_strig(qb_i32 n) { (void)n; return 0; }
qb_i32 qb_pen(qb_i32 n) { (void)n; return 0; }
