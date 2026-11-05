/* screen.c - SCREEN modes, text output, palette, graphics primitives, DRAW, GET/PUT.
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */
#include "qbrt_int.h"
#include <ctype.h>

qbscreen qb_scr;
pthread_mutex_t qb_scr_lock = PTHREAD_MUTEX_INITIALIZER;

typedef struct { int mode, w, h, cols, rows, cw, ch, ncolors, pages, bits, planes; } modeinfo;
static const modeinfo modes[] = {
    { 0, 720, 400, 80, 25, 9, 16, 16, 8, 0, 0 },
    { 1, 320, 200, 40, 25, 8, 8, 4, 1, 2, 1 },
    { 2, 640, 200, 80, 25, 8, 8, 2, 1, 1, 1 },
    { 3, 720, 348, 80, 25, 9, 14, 2, 2, 1, 1 },
    { 4, 640, 400, 80, 25, 8, 16, 2, 1, 1, 1 },
    { 7, 320, 200, 40, 25, 8, 8, 16, 8, 1, 4 },
    { 8, 640, 200, 80, 25, 8, 8, 16, 4, 1, 4 },
    { 9, 640, 350, 80, 25, 8, 14, 16, 2, 1, 4 },
    { 10, 640, 350, 80, 25, 8, 14, 4, 2, 1, 2 },
    { 11, 640, 480, 80, 30, 8, 16, 2, 1, 1, 1 },
    { 12, 640, 480, 80, 30, 8, 16, 16, 1, 1, 4 },
    { 13, 320, 200, 40, 25, 8, 8, 256, 1, 8, 1 },
    { -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 }
};

static uint32_t rgb6(int r, int g, int b)
{
    r &= 63; g &= 63; b &= 63;
    return ((uint32_t)(r * 255 / 63) << 16) | ((uint32_t)(g * 255 / 63) << 8) | (uint32_t)(b * 255 / 63);
}
/* EGA 64-colour palette: bits 0..5 = B G R b g r */
uint32_t qbs_ega_rgb(int c)
{
    int b = ((c & 1) ? 0x2a : 0) + ((c & 8) ? 0x15 : 0);
    int g = ((c & 2) ? 0x2a : 0) + ((c & 16) ? 0x15 : 0);
    int r = ((c & 4) ? 0x2a : 0) + ((c & 32) ? 0x15 : 0);
    return rgb6(r, g, b);
}
/* 16 CGA colours */
static uint32_t cga_rgb(int c)
{
    static const int e[16] = { 0, 1, 2, 3, 4, 5, 20, 7, 56, 57, 58, 59, 60, 61, 62, 63 };
    return qbs_ega_rgb(e[c & 15]);
}

static void set_cga1_palette(void)
{
    /* SCREEN 1: attribute 0 = background colour, 1..3 from palette 0 or 1 (bright) */
    static const int p0[3] = { 10, 12, 14 }, p1[3] = { 11, 13, 15 };
    qb_scr.pal[0] = cga_rgb(qb_scr.cga_bg);
    for (int i = 0; i < 3; i++) qb_scr.pal[i + 1] = cga_rgb(qb_scr.cga_pal ? p1[i] : p0[i]);
}

void qbs_reset_palette(void)
{
    qbscreen *s = &qb_scr;
    for (int i = 0; i < 256; i++) s->pal[i] = 0;
    switch (s->mode) {
    case 0: case 7: case 8: case 9: case 12:
        for (int i = 0; i < 16; i++) { s->pal[i] = cga_rgb(i); s->egapal[i] = i; }
        break;
    case 1: s->cga_pal = 1; s->cga_bg = 0; set_cga1_palette(); break;
    case 2: case 3: case 4: case 11: s->pal[0] = 0; s->pal[1] = 0xFFFFFF; break;
    case 10: s->pal[0] = 0; s->pal[1] = 0x808080; s->pal[2] = 0xC0C0C0; s->pal[3] = 0xFFFFFF; break;
    case 13:
        for (int i = 0; i < 256; i++) s->pal[i] = rgb6(qb_vga_default_pal[i * 3], qb_vga_default_pal[i * 3 + 1], qb_vga_default_pal[i * 3 + 2]);
        break;
    }
    s->dirty = 1;
}

static void free_pages(void)
{
    for (int i = 0; i < QB_MAXPAGES; i++) { free(qb_scr.pix[i]); qb_scr.pix[i] = NULL; free(qb_scr.txt[i]); qb_scr.txt[i] = NULL; }
}

static int default_rows_region(void) { return qb_scr.rows - 1; }

static void reset_view(void)
{
    qbscreen *s = &qb_scr;
    s->vx1 = 0; s->vy1 = 0; s->vx2 = s->w - 1; s->vy2 = s->h - 1; s->view_screen = 0;
    s->win = 0;
    s->lx = s->w / 2; s->ly = s->h / 2;
}

static void set_mode(const modeinfo *m, int cols, int rows)
{
    qbscreen *s = &qb_scr;
    pthread_mutex_lock(&qb_scr_lock);
    free_pages();
    s->mode = m->mode; s->text = m->mode == 0;
    s->cols = cols ? cols : m->cols; s->rows = rows ? rows : m->rows;
    s->cw = m->cw; s->ch = m->ch;
    if (s->text) {
        s->cw = 9;
        s->ch = s->rows <= 25 ? 16 : (s->rows <= 43 ? 8 : 8);
        s->font = s->ch == 16 ? qb_font_16 : qb_font_08;
        s->w = s->cols * s->cw; s->h = s->rows * s->ch;
        if (s->rows == 43) s->h = 43 * 8;
    } else {
        s->w = m->w; s->h = m->h;
        if (m->mode == 11 || m->mode == 12) { s->ch = s->rows == 60 ? 8 : 16; }
        if (m->mode == 9 || m->mode == 10) { s->ch = s->rows == 43 ? 8 : 14; }
        s->cw = s->w / s->cols;
        s->font = s->ch == 16 ? qb_font_16 : s->ch == 14 ? qb_font_14 : qb_font_08;
    }
    s->ncolors = m->ncolors; s->bits = m->bits; s->planes = m->planes;
    s->npages = m->pages;
    if (s->text && s->cols == 40) s->npages = 8;
    s->apage = s->vpage = 0;
    for (int p = 0; p < s->npages; p++) {
        s->txt[p] = malloc(sizeof(uint16_t) * s->cols * s->rows);
        for (int i = 0; i < s->cols * s->rows; i++) s->txt[p][i] = 0x0720;
        if (!s->text) s->pix[p] = calloc(1, (size_t)s->w * s->h);
    }
    s->crow = 0; s->ccol = 0;
    s->vtop = 0; s->vbot = default_rows_region() - 1;
    if (s->vbot < 0) s->vbot = 0;
    s->vbot = s->rows - 2;
    if (s->vbot < s->vtop) s->vbot = s->vtop;
    s->fg = s->text ? 7 : (s->ncolors - 1 > 15 ? 15 : s->ncolors - 1);
    s->bg = 0;
    s->cursor_on = 0;
    s->draw_angle = 0; s->draw_scale = 4; s->draw_ta = 0; s->draw_tav = 0;
    qbs_reset_palette();
    reset_view();
    s->dirty = 1;
    pthread_mutex_unlock(&qb_scr_lock);
    qbd_mode_changed();
}

void qbs_init(void)
{
    memset(&qb_scr, 0, sizeof qb_scr);
    set_mode(&modes[0], 80, 25);
}

static const modeinfo *find_mode(int m)
{
    for (int i = 0; modes[i].mode >= 0; i++) if (modes[i].mode == m) return &modes[i];
    return NULL;
}

void qb_screen(qb_i32 mode, qb_i32 colorswitch, qb_i32 apage, qb_i32 vpage)
{
    (void)colorswitch;
    qbscreen *s = &qb_scr;
    if (mode != QB_NA) {
        const modeinfo *m = find_mode(mode);
        if (!m) { qb_error(5); return; }
        if (mode != s->mode) set_mode(m, 0, 0);
        else if (mode == 0 && s->cols != 80 && apage == QB_NA) { /* SCREEN 0 keeps width */ }
    }
    if (apage != QB_NA) { if (apage < 0 || apage >= s->npages) { qb_error(5); return; } s->apage = apage; if (vpage == QB_NA) vpage = s->vpage; }
    if (vpage != QB_NA) { if (vpage < 0 || vpage >= s->npages) { qb_error(5); return; } s->vpage = vpage; }
    s->dirty = 1;
    qbd_dirty();
}

void qb_width(qb_i32 cols, qb_i32 rows)
{
    qbscreen *s = &qb_scr;
    if (cols == QB_NA) cols = s->cols;
    if (rows == QB_NA) rows = s->rows;
    if (s->text) {
        if ((cols != 40 && cols != 80) || (rows != 25 && rows != 43 && rows != 50)) { qb_error(5); return; }
        if (cols != s->cols || rows != s->rows) set_mode(&modes[0], cols, rows);
        return;
    }
    switch (s->mode) {
    case 1: case 7: case 13: if (cols == 80 && (s->mode == 1 || s->mode == 7)) { set_mode(find_mode(s->mode == 1 ? 2 : 8), 0, 0); return; } break;
    case 2: case 8: if (cols == 40) { set_mode(find_mode(s->mode == 2 ? 1 : 7), 0, 0); return; } break;
    case 9: case 10: if (rows == 43 || rows == 25) { set_mode(find_mode(s->mode), 80, rows); return; } break;
    case 11: case 12: if (rows == 30 || rows == 60) { set_mode(find_mode(s->mode), 80, rows); return; } break;
    }
    if (cols != s->cols || rows != s->rows) qb_error(5);
}

void qb_width_dev(qbs dev, qb_i32 w) { (void)dev; (void)w; }

int qbs_text_width(void) { return qb_scr.cols; }

/* ------------------------------------------------------------------ */
/* text output                                                         */
static inline int text_attr(void)
{
    qbscreen *s = &qb_scr;
    int fg = s->fg, bg = s->bg;
    int a = (fg & 15) | ((bg & 7) << 4);
    if (fg & 16) a |= 0x80;
    return a;
}

void qbs_gfx_text_cell(int row, int col, int c, int fg, int bg)
{
    qbscreen *s = &qb_scr;
    unsigned char *pg = s->pix[s->apage];
    if (!pg) return;
    const unsigned char *glyph = s->font + c * s->ch;
    int x0 = col * s->cw, y0 = row * s->ch;
    for (int y = 0; y < s->ch && y0 + y < s->h; y++) {
        unsigned char bits = glyph[y];
        unsigned char *p = pg + (size_t)(y0 + y) * s->w + x0;
        for (int x = 0; x < 8 && x0 + x < s->w; x++) p[x] = (bits & (0x80 >> x)) ? fg : bg;
        for (int x = 8; x < s->cw && x0 + x < s->w; x++) p[x] = bg;
    }
}

void qbs_set_text_cell(int row, int col, int c, int attr)
{
    qbscreen *s = &qb_scr;
    if (row < 0 || row >= s->rows || col < 0 || col >= s->cols) return;
    if (attr < 0) attr = s->text ? text_attr() : s->fg;
    s->txt[s->apage][row * s->cols + col] = (uint16_t)((c & 0xFF) | (attr << 8));
    if (!s->text) qbs_gfx_text_cell(row, col, c & 0xFF, attr & 0xFF, 0);
    s->dirty = 1;
}

void qbs_text_scroll_region(int top, int bot)
{
    qbscreen *s = &qb_scr;
    uint16_t *t = s->txt[s->apage];
    if (bot > top) memmove(t + top * s->cols, t + (top + 1) * s->cols, sizeof(uint16_t) * s->cols * (bot - top));
    int blank = s->text ? (0x20 | (((s->bg & 7) << 4 | 7) << 8)) : 0x0020;
    if (s->text) blank = 0x20 | ((((s->bg & 7) << 4) | (s->fg & 15)) << 8);
    for (int c = 0; c < s->cols; c++) t[bot * s->cols + c] = (uint16_t)blank;
    if (!s->text && s->pix[s->apage]) {
        unsigned char *p = s->pix[s->apage];
        size_t rowbytes = (size_t)s->w * s->ch;
        if (bot > top) memmove(p + top * rowbytes, p + (top + 1) * rowbytes, rowbytes * (bot - top));
        int y1 = (bot + 1) * s->ch; if (y1 > s->h) y1 = s->h;
        memset(p + (size_t)bot * rowbytes, 0, (size_t)(y1 - bot * s->ch) * s->w);
    }
    s->dirty = 1;
}

void qbs_scroll(void) { qbs_text_scroll_region(qb_scr.vtop, qb_scr.vbot); }

void qbs_newline(void)
{
    qbscreen *s = &qb_scr;
    if (qb_mode_display == QBD_STREAM) { fputc('\n', stdout); s->ccol = 0; return; }
    s->ccol = 0;
    if (s->crow >= s->vbot) {
        if (s->crow > s->vbot) s->crow = s->vbot;
        qbs_scroll();
    } else s->crow++;
    s->dirty = 1;
    qbd_console_write("\n", 1);
}

void qbs_putc(int c)
{
    qbscreen *s = &qb_scr;
    c &= 0xFF;
    if (qb_mode_display == QBD_STREAM) {
        if (c == 13) { fputc('\n', stdout); s->ccol = 0; return; }
        if (c == 7) return;
        { extern void qbd_stream_putc(int); qbd_stream_putc(c); }
        if (++s->ccol >= s->cols) { s->ccol = 0; fputc('\n', stdout); }
        return;
    }
    switch (c) {
    case 7: qb_beep(); return;
    case 9: { int n = 8 - (s->ccol % 8); while (n--) qbs_putc(' '); return; }
    case 10: case 13: qbs_newline(); return;
    case 11: s->crow = s->vtop; s->ccol = 0; return;
    case 12: qb_cls(QB_NA); return;
    case 28: if (s->ccol < s->cols - 1) s->ccol++; return;
    case 29: if (s->ccol > 0) s->ccol--; return;
    case 30: if (s->crow > s->vtop) s->crow--; return;
    case 31: if (s->crow < s->vbot) s->crow++; return;
    }
    if (s->ccol >= s->cols) qbs_newline();
    qbs_set_text_cell(s->crow, s->ccol, c, -1);
    s->ccol++;
    if (s->ccol >= s->cols) qbs_newline();
}

void qbs_write(const char *str, int n)
{
    for (int i = 0; i < n; i++) qbs_putc((unsigned char)str[i]);
    qb_scr.dirty = 1;
}

void qbs_cls_region(int top, int bot)
{
    qbscreen *s = &qb_scr;
    uint16_t *t = s->txt[s->apage];
    int blank = s->text ? (0x20 | ((((s->bg & 7) << 4) | (s->fg & 15)) << 8)) : 0x0020;
    for (int r = top; r <= bot; r++) for (int c = 0; c < s->cols; c++) t[r * s->cols + c] = (uint16_t)blank;
    if (!s->text) {
        unsigned char *p = s->pix[s->apage];
        int y0 = top * s->ch, y1 = (bot + 1) * s->ch; if (y1 > s->h) y1 = s->h;
        memset(p + (size_t)y0 * s->w, 0, (size_t)(y1 - y0) * s->w);
    }
    s->dirty = 1;
}

static void gfx_clear_view(int color);

void qb_cls(qb_i32 mode)
{
    qbscreen *s = &qb_scr;
    if (qb_mode_display == QBD_STREAM) { if (qb_line_tty) { qbd_line_cls(); s->ccol = 0; } return; }
    if (mode == QB_NA) {
        /* graphics viewport active -> clear it, else text viewport... QB: clears the active viewport */
        if (!s->text && (s->vx1 != 0 || s->vy1 != 0 || s->vx2 != s->w - 1 || s->vy2 != s->h - 1)) mode = 1;
        else if (s->vtop != 0 || s->vbot != s->rows - 2) mode = 2;
        else mode = 0;
    }
    if (mode == 0) {
        qbs_cls_region(0, s->rows - 1);
        s->crow = s->vtop; s->ccol = 0;
        if (!s->text) { s->lx = s->win ? (s->wx1 + s->wx2) / 2 : (s->vx2 - s->vx1) / 2; s->ly = s->win ? (s->wy1 + s->wy2) / 2 : (s->vy2 - s->vy1) / 2; }
    } else if (mode == 1) {
        if (!s->text) gfx_clear_view(0);
        else qbs_cls_region(0, s->rows - 1);
    } else if (mode == 2) {
        qbs_cls_region(s->vtop, s->vbot);
        s->crow = s->vtop; s->ccol = 0;
    } else { qb_error(5); return; }
    s->dirty = 1;
    qbd_dirty();
}

void qb_locate(qb_i32 row, qb_i32 col, qb_i32 cursor, qb_i32 start, qb_i32 stop)
{
    qbscreen *s = &qb_scr;
    if (row != QB_NA || col != QB_NA) qbd_need_screen();
    if (row != QB_NA) {
        if (row < 1 || row > s->rows) { qb_error(5); return; }
        if (row - 1 < s->vtop || (row - 1 > s->vbot && row != s->rows)) { qb_error(5); return; }
        s->crow = row - 1;
    }
    if (col != QB_NA) {
        if (col < 1 || col > s->cols) { qb_error(5); return; }
        s->ccol = col - 1;
    }
    if (cursor != QB_NA) s->cursor_on = cursor != 0;
    if (start != QB_NA) s->cur_start = start;
    if (stop != QB_NA) s->cur_stop = stop;
    if (qb_mode_display == QBD_STREAM && col != QB_NA && row == QB_NA) { }
    s->dirty = 1;
}

qb_i32 qb_csrlin(void) { return qb_scr.crow + 1; }
qb_i32 qb_pos(qb_i32 d) { (void)d; return qb_scr.ccol >= qb_scr.cols ? qb_scr.cols : qb_scr.ccol + 1; }
qb_i32 qb_lpos(qb_i32 d) { (void)d; return 1; }

void qb_view_print(qb_i32 top, qb_i32 bottom)
{
    qbscreen *s = &qb_scr;
    if (top != QB_NA) qbd_need_screen();
    if (top == QB_NA) { s->vtop = 0; s->vbot = s->rows - 2; }
    else {
        if (top < 1 || bottom > s->rows || top > bottom) { qb_error(5); return; }
        s->vtop = top - 1; s->vbot = bottom - 1;
    }
    s->crow = s->vtop; s->ccol = 0;
}

qb_i32 qb_screen_fn(qb_i32 row, qb_i32 col, qb_i32 flag)
{
    qbscreen *s = &qb_scr;
    if (row < 1 || row > s->rows || col < 1 || col > s->cols) { qb_error(5); return 0; }
    uint16_t v = s->txt[s->apage][(row - 1) * s->cols + col - 1];
    if (flag != QB_NA && flag != 0) return s->text ? (v >> 8) : 0;
    return v & 0xFF;
}

void qb_color(qb_i32 fg, qb_i32 bg, qb_i32 border)
{
    qbscreen *s = &qb_scr;
    switch (s->mode) {
    case 0:
        if (fg != QB_NA) { if (fg < 0 || fg > 31) { qb_error(5); return; } s->fg = fg; }
        if (bg != QB_NA) { if (bg < 0 || bg > 15) { qb_error(5); return; } s->bg = bg & 7; }
        if (border != QB_NA) s->border = border;
        if (qb_line_tty) qbd_line_color(s->fg, s->bg);
        break;
    case 1:
        if (fg != QB_NA) { if (fg < 0 || fg > 255) { qb_error(5); return; } s->cga_bg = fg & 15; }
        if (bg != QB_NA) s->cga_pal = bg & 1;
        set_cga1_palette();
        break;
    case 7: case 8: case 9:
        if (fg != QB_NA) { if (fg < 0 || fg > 15) { qb_error(5); return; } s->fg = fg; }
        if (bg != QB_NA) {
            int maxc = s->mode == 9 ? 63 : 15;
            if (bg < 0 || bg > maxc) { qb_error(5); return; }
            s->pal[0] = s->mode == 9 ? qbs_ega_rgb(bg) : cga_rgb(bg);
        }
        break;
    case 10:
        if (fg != QB_NA) { if (fg < 0 || fg > 3) { qb_error(5); return; } s->fg = fg; }
        break;
    case 12: case 13:
        if (bg != QB_NA) { qb_error(5); return; }
        if (fg != QB_NA) { if (fg < 0 || fg >= s->ncolors) { qb_error(5); return; } s->fg = fg; }
        break;
    default:
        qb_error(5); return;
    }
    s->dirty = 1;
}

void qb_palette(qb_i32 attr, qb_i32 color)
{
    qbscreen *s = &qb_scr;
    if (attr == QB_NA) { qbs_reset_palette(); return; }
    if (attr < 0 || attr >= (s->text ? 16 : s->ncolors)) { qb_error(5); return; }
    if (color == -1) return;
    switch (s->mode) {
    case 0: case 7: case 8:
        if (color < 0 || color > (s->mode == 0 ? 63 : 15)) { qb_error(5); return; }
        s->pal[attr] = s->mode == 0 ? qbs_ega_rgb(color) : cga_rgb(color);
        if (s->mode == 0 && color < 16 && color != 6) s->pal[attr] = qbs_ega_rgb(color);
        break;
    case 9:
        if (color < 0 || color > 63) { qb_error(5); return; }
        s->pal[attr] = qbs_ega_rgb(color); break;
    case 10:
        s->pal[attr] = color == 0 ? 0 : color < 3 ? 0x808080 : color < 6 ? 0xC0C0C0 : 0xFFFFFF; break;
    case 11: case 12: case 13:
        if (color < 0 || color > 0x3F3F3F) { qb_error(5); return; }
        s->pal[attr] = rgb6(color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF); break;
    default: qb_error(5); return;
    }
    s->dirty = 1;
}
void qb_palette_reset(void) { qbs_reset_palette(); }
void qb_palette_using(void *elem, qb_i32 esz, qb_i32 count)
{
    qbscreen *s = &qb_scr;
    int n = s->text ? 16 : s->ncolors;
    if (n > 256) n = 256;
    for (int i = 0; i < n && i < count; i++) {
        int c = esz == 2 ? ((qb_i16 *)elem)[i] : ((qb_i32 *)elem)[i];
        if (c >= 0) qb_palette(i, c);
    }
}

void qb_pcopy(qb_i32 src, qb_i32 dst)
{
    qbscreen *s = &qb_scr;
    qbd_need_screen();
    if (src < 0 || src >= s->npages || dst < 0 || dst >= s->npages) { qb_error(5); return; }
    memcpy(s->txt[dst], s->txt[src], sizeof(uint16_t) * s->cols * s->rows);
    if (!s->text) memcpy(s->pix[dst], s->pix[src], (size_t)s->w * s->h);
    s->dirty = 1;
}

void qb_key_onoff(qb_i32 on) { qb_scr.keyline = on; qb_scr.dirty = 1; }
void qb_key_list(void) { for (int i = 1; i <= 10; i++) { char b[16]; int n = snprintf(b, sizeof b, "F%d", i); qbs_write(b, n); qbs_newline(); } }

void qbs_cursor_blink_reset(void) {}

/* ------------------------------------------------------------------ */
/* graphics coordinates                                                */
static inline int need_gfx(void)
{
    if (qb_scr.text) { qb_error(5); return 0; }
    return 1;
}

static void log2phys(double x, double y, double *px, double *py)
{
    qbscreen *s = &qb_scr;
    double vw = s->vx2 - s->vx1, vh = s->vy2 - s->vy1;
    if (s->win) {
        *px = (x - s->wx1) * vw / (s->wx2 - s->wx1);
        if (s->win_screen) *py = (y - s->wy1) * vh / (s->wy2 - s->wy1);
        else *py = (s->wy2 - y) * vh / (s->wy2 - s->wy1);
    } else { *px = x; *py = y; }
    if (!s->view_screen) { *px += s->vx1; *py += s->vy1; }
    else if (s->win) { *px += s->vx1; *py += s->vy1; }
}
static void phys2log(double px, double py, double *x, double *y)
{
    qbscreen *s = &qb_scr;
    double vw = s->vx2 - s->vx1, vh = s->vy2 - s->vy1;
    if (!s->view_screen || s->win) { px -= s->vx1; py -= s->vy1; }
    if (s->win) {
        *x = s->wx1 + px * (s->wx2 - s->wx1) / (vw ? vw : 1);
        if (s->win_screen) *y = s->wy1 + py * (s->wy2 - s->wy1) / (vh ? vh : 1);
        else *y = s->wy2 - py * (s->wy2 - s->wy1) / (vh ? vh : 1);
    } else { *x = px; *y = py; }
}

static inline int iround(double v) { return (int)floor(v + 0.5); }

static inline void putpix(int x, int y, int c)
{
    qbscreen *s = &qb_scr;
    if (x < s->vx1 || x > s->vx2 || y < s->vy1 || y > s->vy2) return;
    if (x < 0 || y < 0 || x >= s->w || y >= s->h) return;
    s->pix[s->apage][(size_t)y * s->w + x] = (unsigned char)(c & (s->ncolors - 1));
}
static inline int getpix(int x, int y)
{
    qbscreen *s = &qb_scr;
    if (x < 0 || y < 0 || x >= s->w || y >= s->h) return -1;
    return s->pix[s->apage][(size_t)y * s->w + x];
}

static int color_or_fg(int c) { return c == QB_NA ? qb_scr.fg : c; }

static void gfx_clear_view(int color)
{
    qbscreen *s = &qb_scr;
    for (int y = s->vy1; y <= s->vy2; y++)
        if (y >= 0 && y < s->h) memset(s->pix[s->apage] + (size_t)y * s->w + (s->vx1 < 0 ? 0 : s->vx1), color, (size_t)(s->vx2 - s->vx1 + 1));
    s->lx = s->win ? (s->wx1 + s->wx2) / 2 : (s->vx2 - s->vx1) / 2;
    s->ly = s->win ? (s->wy1 + s->wy2) / 2 : (s->vy2 - s->vy1) / 2;
    s->dirty = 1;
}

void qb_pset(qb_i32 step, double x, double y, qb_i32 color, qb_i32 preset)
{
    qbscreen *s = &qb_scr;
    if (!need_gfx()) return;
    if (step) { x += s->lx; y += s->ly; }
    s->lx = x; s->ly = y;
    double px, py; log2phys(x, y, &px, &py);
    int c = color == QB_NA ? (preset ? 0 : s->fg) : color;
    putpix(iround(px), iround(py), c);
    s->dirty = 1;
}

static void hline(int x1, int x2, int y, int c)
{
    qbscreen *s = &qb_scr;
    if (y < s->vy1 || y > s->vy2) return;
    if (x1 > x2) { int t = x1; x1 = x2; x2 = t; }
    if (x1 < s->vx1) x1 = s->vx1;
    if (x2 > s->vx2) x2 = s->vx2;
    if (x1 < 0) x1 = 0;
    if (x2 >= s->w) x2 = s->w - 1;
    if (y < 0 || y >= s->h || x1 > x2) return;
    memset(s->pix[s->apage] + (size_t)y * s->w + x1, c & (s->ncolors - 1), (size_t)(x2 - x1 + 1));
}

static unsigned style_bit;
/* QB line rasterisation (reconstructed from QB 4.5 output): lines are drawn
 * from the right-hand endpoint, Bresenham with the error term starting at (M-1)/2. */
static void line_raw(int x1, int y1, int x2, int y2, int c, int style)
{
    if (x1 < x2) { int t = x1; x1 = x2; x2 = t; t = y1; y1 = y2; y2 = t; }
    int dx = abs(x2 - x1), dy = abs(y2 - y1);
    int sx = x2 < x1 ? -1 : 1, sy = y2 > y1 ? 1 : -1;
    int plain = (style == 0xFFFF || style == -1 || style == QB_NA);
    int M = dx >= dy ? dx : dy, m = dx >= dy ? dy : dx;
    int e = (M - 1) / 2, x = x1, y = y1;
    for (int k = 0; k <= M; k++) {
        if (plain) putpix(x, y, c);
        else { if (style & (0x8000 >> (style_bit & 15))) putpix(x, y, c); style_bit++; }
        e += 2 * m;
        if (dx >= dy) { x += sx; if (e >= 2 * M) { e -= 2 * M; y += sy; } }
        else { y += sy; if (e >= 2 * M) { e -= 2 * M; x += sx; } }
    }
}

void qb_line(qb_i32 flags, double x1, double y1, double x2, double y2, qb_i32 color, qb_i32 box, qb_i32 style)
{
    qbscreen *s = &qb_scr;
    if (!need_gfx()) return;
    if (flags & 4) { x1 = s->lx; y1 = s->ly; }      /* first point omitted */
    else if (flags & 1) { x1 += s->lx; y1 += s->ly; }
    if (flags & 2) { x2 += x1; y2 += y1; }
    s->lx = x2; s->ly = y2;
    double a, b, c2, d;
    log2phys(x1, y1, &a, &b); log2phys(x2, y2, &c2, &d);
    int ix1 = iround(a), iy1 = iround(b), ix2 = iround(c2), iy2 = iround(d);
    int c = color_or_fg(color);
    if (style != QB_NA) style &= 0xFFFF;
    style_bit = 1;
    if (box == 2) {
        if (iy1 > iy2) { int t = iy1; iy1 = iy2; iy2 = t; }
        for (int y = iy1; y <= iy2; y++) hline(ix1, ix2, y, c);
    } else if (box == 1) {
        line_raw(ix1, iy1, ix2, iy1, c, style);
        line_raw(ix1, iy2, ix2, iy2, c, style);
        line_raw(ix1, iy1, ix1, iy2, c, style);
        line_raw(ix2, iy1, ix2, iy2, c, style);
    } else line_raw(ix1, iy1, ix2, iy2, c, style);
    s->dirty = 1;
}

static double default_aspect(void)
{
    qbscreen *s = &qb_scr;
    return (4.0 / 3.0) * ((double)s->h / (double)s->w);
}

/* QB keeps the aspect ratio in fixed point (truncated) */
static double fix_aspect(double a) { return floor(a * 65536.0) / 65536.0; }

static void circle_plot4(int cx, int cy, int X, int Y, int c, int arc, double a0, double a1)
{
    int pts[4][2] = { { X, Y }, { -X, Y }, { X, -Y }, { -X, -Y } };
    for (int i = 0; i < 4; i++) {
        if (i > 0 && ((i == 1 && X == 0) || (i == 2 && Y == 0) || (i == 3 && (X == 0 || Y == 0)))) continue;
        int px = pts[i][0], py = pts[i][1];
        if (arc) {
            double ang = atan2(-(double)py, (double)px);
            if (ang < 0) ang += 2 * M_PI;
            int in = a0 <= a1 ? (ang >= a0 - 1e-5 && ang <= a1 + 1e-5) : (ang >= a0 - 1e-5 || ang <= a1 + 1e-5);
            if (!in) continue;
        }
        putpix(cx + px, cy + py, c);
    }
}

void qb_circle(qb_i32 step, double x, double y, double r, qb_i32 color, double start, double end, double aspect)
{
    qbscreen *s = &qb_scr;
    if (!need_gfx()) return;
    if (step) { x += s->lx; y += s->ly; }
    s->lx = x; s->ly = y;
    int c = color_or_fg(color);
    if (aspect == QB_NAD) aspect = default_aspect();
    if (aspect < 0) aspect = -aspect;
    aspect = fix_aspect(aspect);
    double cx, cy; log2phys(x, y, &cx, &cy);
    double rpx = r;
    if (s->win) rpx = r * (s->vx2 - s->vx1) / fabs(s->wx2 - s->wx1);
    int R = (int)floor(fabs(rpx) + 0.5);
    int icx = iround(cx), icy = iround(cy);
    int arc = !(start == QB_NAD && end == QB_NAD);
    double a0 = start == QB_NAD ? 0 : start, a1 = end == QB_NAD ? 2 * M_PI : end;
    int line0 = 0, line1 = 0;
    if (a0 < 0) { line0 = 1; a0 = -a0; }
    if (a1 < 0) { line1 = 1; a1 = -a1; }
    if (a0 > 2 * M_PI + 1e-6 || a1 > 2 * M_PI + 1e-6) { qb_error(5); return; }
    if (arc && a0 == 0 && a1 >= 2 * M_PI - 1e-9) arc = 0;
    /* rasterise a circle of radius R, then scale the minor axis by the aspect ratio */
    for (int i = 0; i <= R; i++) {
        int j = (int)floor(sqrt((double)R * R - (double)i * i) + 0.5);
        int P[2][2] = { { i, j }, { j, i } };
        for (int k = 0; k < 2; k++) {
            int X = P[k][0], Y = P[k][1];
            if (aspect <= 1) Y = (int)floor(Y * aspect + 0.5);
            else X = (int)floor(X / aspect + 0.5);
            circle_plot4(icx, icy, X, Y, c, arc, a0, a1);
        }
    }
    if (line0 || line1) {
        double rx = aspect <= 1 ? R : R / aspect, ry = aspect <= 1 ? R * aspect : R;
        if (line0) line_raw(icx, icy, icx + iround(rx * cos(a0)), icy - iround(ry * sin(a0)), c, QB_NA);
        if (line1) line_raw(icx, icy, icx + iround(rx * cos(a1)), icy - iround(ry * sin(a1)), c, QB_NA);
    }
    s->dirty = 1;
}

/* ---- PAINT --------------------------------------------------------------- */
static int tile_color(qbs tile, int x, int y)
{
    qbscreen *s = &qb_scr;
    if (tile.len == 0) return s->fg;
    int bpp = s->mode == 1 ? 2 : (s->mode == 13 ? 8 : 1);
    int planes = s->planes > 1 ? s->planes : 1;
    if (s->mode == 13) { int row = y % tile.len; return (unsigned char)tile.p[row]; }
    if (planes > 1) {
        int rows = tile.len / planes; if (rows < 1) rows = 1;
        int row = y % rows; int bit = 7 - (x & 7), col = 0;
        for (int p = 0; p < planes; p++) {
            int idx = row * planes + p;
            if (idx < tile.len && (tile.p[idx] >> bit) & 1) col |= 1 << p;
        }
        return col;
    }
    int row = y % tile.len;
    unsigned char b = (unsigned char)tile.p[row];
    if (bpp == 2) { int pos = x & 3; return (b >> (6 - pos * 2)) & 3; }
    return (b >> (7 - (x & 7))) & 1;
}

void qb_paint(qb_i32 step, double x, double y, qb_i32 color, qbs tile, qb_i32 has_tile, qb_i32 border, qbs bg, qb_i32 has_bg)
{
    qbscreen *s = &qb_scr;
    (void)bg; (void)has_bg;
    if (!need_gfx()) return;
    if (step) { x += s->lx; y += s->ly; }
    s->lx = x; s->ly = y;
    double px, py; log2phys(x, y, &px, &py);
    int sx = iround(px), sy = iround(py);
    int paintc = has_tile ? -1 : color_or_fg(color);
    int bord = border == QB_NA ? (has_tile ? s->fg : paintc) : border;
    if (has_tile && tile.len == 0) { qb_error(5); return; }
    if (sx < s->vx1 || sx > s->vx2 || sy < s->vy1 || sy > s->vy2) return;
    if (getpix(sx, sy) == bord) return;
    int W = s->w, H = s->h;
    unsigned char *seen = calloc((size_t)W * H, 1);
    int cap = 4096, n = 0;
    int *stk = malloc(sizeof(int) * 2 * cap);
    stk[n++] = sx; stk[n++] = sy;
    while (n > 0) {
        int yy = stk[--n], xx = stk[--n];
        if (yy < s->vy1 || yy > s->vy2) continue;
        if (seen[(size_t)yy * W + xx] || getpix(xx, yy) == bord) continue;
        int l = xx, r = xx;
        while (l - 1 >= s->vx1 && !seen[(size_t)yy * W + l - 1] && getpix(l - 1, yy) != bord) l--;
        while (r + 1 <= s->vx2 && !seen[(size_t)yy * W + r + 1] && getpix(r + 1, yy) != bord) r++;
        for (int i = l; i <= r; i++) {
            seen[(size_t)yy * W + i] = 1;
            putpix(i, yy, paintc >= 0 ? paintc : tile_color(tile, i, yy));
        }
        for (int dir = -1; dir <= 1; dir += 2) {
            int ny = yy + dir;
            if (ny < s->vy1 || ny > s->vy2) continue;
            int i = l;
            while (i <= r) {
                while (i <= r && (seen[(size_t)ny * W + i] || getpix(i, ny) == bord)) i++;
                if (i > r) break;
                if (n + 2 >= 2 * cap) { cap *= 2; stk = realloc(stk, sizeof(int) * 2 * cap); }
                stk[n++] = i; stk[n++] = ny;
                while (i <= r && !seen[(size_t)ny * W + i] && getpix(i, ny) != bord) i++;
            }
        }
    }
    free(stk); free(seen);
    s->dirty = 1;
}

qb_i32 qb_point(double x, double y)
{
    qbscreen *s = &qb_scr;
    if (!need_gfx()) return 0;
    double px, py; log2phys(x, y, &px, &py);
    int ix = iround(px), iy = iround(py);
    if (ix < s->vx1 || ix > s->vx2 || iy < s->vy1 || iy > s->vy2) return -1;
    return getpix(ix, iy);
}
float qb_point_n(qb_i32 n)
{
    qbscreen *s = &qb_scr;
    double px, py; log2phys(s->lx, s->ly, &px, &py);
    switch (n) {
    case 0: return (float)iround(px - (s->view_screen ? 0 : s->vx1));
    case 1: return (float)iround(py - (s->view_screen ? 0 : s->vy1));
    case 2: return (float)s->lx;
    case 3: return (float)s->ly;
    }
    qb_error(5); return 0;
}

void qb_view(qb_i32 screenflag, double x1, double y1, double x2, double y2, qb_i32 fill, qb_i32 border, qb_i32 off)
{
    qbscreen *s = &qb_scr;
    if (!need_gfx()) return;
    if (off) { reset_view(); s->win = 0; return; }
    int a = iround(x1), b = iround(y1), c = iround(x2), d = iround(y2);
    if (a > c) { int t = a; a = c; c = t; }
    if (b > d) { int t = b; b = d; d = t; }
    if (a < 0 || b < 0 || c >= s->w || d >= s->h) { qb_error(5); return; }
    s->vx1 = 0; s->vy1 = 0; s->vx2 = s->w - 1; s->vy2 = s->h - 1;
    if (border != QB_NA) {
        line_raw(a - 1, b - 1, c + 1, b - 1, border, QB_NA); line_raw(c + 1, b - 1, c + 1, d + 1, border, QB_NA);
        line_raw(c + 1, d + 1, a - 1, d + 1, border, QB_NA); line_raw(a - 1, d + 1, a - 1, b - 1, border, QB_NA);
    }
    s->vx1 = a; s->vy1 = b; s->vx2 = c; s->vy2 = d; s->view_screen = screenflag;
    if (fill != QB_NA) for (int y = b; y <= d; y++) hline(a, c, y, fill);
    s->lx = s->win ? (s->wx1 + s->wx2) / 2 : (c - a) / 2;
    s->ly = s->win ? (s->wy1 + s->wy2) / 2 : (d - b) / 2;
    s->dirty = 1;
}

void qb_window(qb_i32 screenflag, double x1, double y1, double x2, double y2, qb_i32 off)
{
    qbscreen *s = &qb_scr;
    if (!need_gfx()) return;
    if (off) { s->win = 0; s->lx = (s->vx2 - s->vx1) / 2; s->ly = (s->vy2 - s->vy1) / 2; return; }
    if (x1 == x2 || y1 == y2) { qb_error(5); return; }
    if (x1 > x2) { double t = x1; x1 = x2; x2 = t; }
    if (y1 > y2) { double t = y1; y1 = y2; y2 = t; }
    s->win = 1; s->win_screen = screenflag;
    s->wx1 = x1; s->wy1 = y1; s->wx2 = x2; s->wy2 = y2;
    s->lx = (x1 + x2) / 2; s->ly = (y1 + y2) / 2;
}

double qb_pmap(double v, qb_i32 fn)
{
    qbscreen *s = &qb_scr;
    if (!need_gfx()) return 0;
    double px, py, lx, ly;
    switch (fn) {
    case 0: log2phys(v, s->win ? s->wy1 : 0, &px, &py); return iround(px - s->vx1);
    case 1: log2phys(s->win ? s->wx1 : 0, v, &px, &py); return iround(py - s->vy1);
    case 2: phys2log(v + s->vx1, s->vy1, &lx, &ly); return lx;
    case 3: phys2log(s->vx1, v + s->vy1, &lx, &ly); return ly;
    }
    qb_error(5); return 0;
}

/* ---- DRAW ---------------------------------------------------------------- */
static const char *dp; static int dn;
static int dpeek(void) { while (dn > 0 && (*dp == ' ' || *dp == ';')) { dp++; dn--; } return dn > 0 ? (unsigned char)*dp : -1; }
static int dget(void) { int c = dpeek(); if (c >= 0) { dp++; dn--; } return c; }
static int dnum(double *out)
{
    int c = dpeek();
    if (c == '=') {
        dget();
        if (dn >= 9 && dp[0] == 1) { memcpy(out, dp + 1, 8); dp += 9; dn -= 9; if (dpeek() == ';') dget(); return 1; }
        return 0;
    }
    int neg = 0, any = 0; double v = 0;
    if (c == '+' || c == '-') { neg = c == '-'; dget(); }
    while (dn > 0 && isdigit((unsigned char)*dp)) { v = v * 10 + (*dp - '0'); dp++; dn--; any = 1; }
    *out = neg ? -v : v;
    return any;
}

static void draw_exec(const char *str, int len, int depth);

static void draw_move(double dx, double dy, int nodraw, int noupdate)
{
    qbscreen *s = &qb_scr;
    double ang = s->draw_ta ? s->draw_tav * M_PI / 180.0 : s->draw_angle * M_PI / 2;
    double sc = s->draw_scale / 4.0;
    dx *= sc; dy *= sc;
    if (ang != 0) {
        double c = cos(ang), sn = sin(ang);
        double nx = dx * c + dy * sn, ny = -dx * sn + dy * c;
        dx = nx; dy = ny;
    }
    double px, py; log2phys(s->lx, s->ly, &px, &py);
    double nx = px + dx, ny = py + dy;
    if (!nodraw) line_raw(iround(px), iround(py), iround(nx), iround(ny), s->fg, QB_NA);
    if (!noupdate) phys2log(nx, ny, &s->lx, &s->ly);
}

static void draw_exec(const char *str, int len, int depth)
{
    qbscreen *s = &qb_scr;
    const char *save_p = dp; int save_n = dn;
    dp = str; dn = len;
    if (depth > 16) { qb_error(5); return; }
    for (;;) {
        int c = dget();
        if (c < 0) break;
        c = toupper(c);
        int nodraw = 0, noupd = 0;
        while (c == 'B' || c == 'N') { if (c == 'B') nodraw = 1; else noupd = 1; c = toupper(dget()); }
        double n = 1;
        switch (c) {
        case 'U': if (!dnum(&n)) n = 1; draw_move(0, -n, nodraw, noupd); break;
        case 'D': if (!dnum(&n)) n = 1; draw_move(0, n, nodraw, noupd); break;
        case 'L': if (!dnum(&n)) n = 1; draw_move(-n, 0, nodraw, noupd); break;
        case 'R': if (!dnum(&n)) n = 1; draw_move(n, 0, nodraw, noupd); break;
        case 'E': if (!dnum(&n)) n = 1; draw_move(n, -n, nodraw, noupd); break;
        case 'F': if (!dnum(&n)) n = 1; draw_move(n, n, nodraw, noupd); break;
        case 'G': if (!dnum(&n)) n = 1; draw_move(-n, n, nodraw, noupd); break;
        case 'H': if (!dnum(&n)) n = 1; draw_move(-n, -n, nodraw, noupd); break;
        case 'M': {
            int rel = dpeek() == '+' || dpeek() == '-';
            double x = 0, y = 0;
            dnum(&x); if (dpeek() == ',') dget(); dnum(&y);
            if (rel) draw_move(x, y, nodraw, noupd);
            else {
                double px, py; log2phys(s->lx, s->ly, &px, &py);
                double tx, ty;
                if (!s->view_screen) { tx = x + s->vx1; ty = y + s->vy1; } else { tx = x; ty = y; }
                if (!nodraw) line_raw(iround(px), iround(py), iround(tx), iround(ty), s->fg, QB_NA);
                if (!noupd) phys2log(tx, ty, &s->lx, &s->ly);
            }
            break;
        }
        case 'A': dnum(&n); s->draw_angle = (int)n & 3; s->draw_ta = 0; break;
        case 'T': if (toupper(dget()) == 'A') { dnum(&n); s->draw_tav = n; s->draw_ta = 1; } break;
        case 'C': dnum(&n); s->fg = (int)n; break;
        case 'S': dnum(&n); s->draw_scale = n; break;
        case 'P': {
            double pc = 0, bc = 0; dnum(&pc); if (dpeek() == ',') dget(); dnum(&bc);
            double sxl = s->lx, syl = s->ly;
            qb_paint(0, sxl, syl, (int)pc, qb_slit("", 0), 0, (int)bc, qb_slit("", 0), 0);
            break;
        }
        case 'X': {
            if (dn >= 5 && dp[0] == 2) {
                int l; memcpy(&l, dp + 1, 4);
                const char *sub = dp + 5;
                dp += 5 + l; dn -= 5 + l;
                const char *rp = dp; int rn = dn;
                draw_exec(sub, l, depth + 1);
                dp = rp; dn = rn;
            }
            break;
        }
        default: break;
        }
    }
    dp = save_p; dn = save_n;
}

void qb_draw(qbs cmds)
{
    if (!need_gfx()) return;
    draw_exec(cmds.p, cmds.len, 0);
    qb_scr.dirty = 1;
}

/* ---- GET / PUT (graphics) ------------------------------------------------ */
static int bits_per_pixel_packed(void)
{
    qbscreen *s = &qb_scr;
    return s->planes > 1 ? 1 : s->bits;
}

void qb_gget(qb_i32 flags, double x1, double y1, double x2, double y2, qbarr *a, qb_i32 off)
{
    qbscreen *s = &qb_scr;
    if (!need_gfx()) return;
    if (flags & 1) { x1 += s->lx; y1 += s->ly; }
    if (flags & 2) { x2 += x1; y2 += y1; }
    double p1x, p1y, p2x, p2y; log2phys(x1, y1, &p1x, &p1y); log2phys(x2, y2, &p2x, &p2y);
    int ax = iround(p1x), ay = iround(p1y), bx = iround(p2x), by = iround(p2y);
    if (ax > bx) { int t = ax; ax = bx; bx = t; }
    if (ay > by) { int t = ay; ay = by; by = t; }
    if (ax < 0 || ay < 0 || bx >= s->w || by >= s->h) { qb_error(5); return; }
    int w = bx - ax + 1, h = by - ay + 1;
    int bpp = bits_per_pixel_packed(), planes = s->planes > 1 ? s->planes : 1;
    int rowbytes = (w * bpp + 7) / 8;
    long need = 4 + (long)rowbytes * planes * h;
    unsigned char *base = (unsigned char *)a->data + (long)off * a->esz;
    long avail = ((long)a->n - off) * a->esz;
    if (!a->data || need > avail) { qb_error(5); return; }
    qb_i16 hw = (qb_i16)(planes > 1 ? w : w * bpp), hh = (qb_i16)h;
    memcpy(base, &hw, 2); memcpy(base + 2, &hh, 2);
    unsigned char *o = base + 4;
    for (int y = 0; y < h; y++) {
        for (int p = 0; p < planes; p++) {
            memset(o, 0, rowbytes);
            for (int x = 0; x < w; x++) {
                int c = getpix(ax + x, ay + y);
                if (planes > 1) { if ((c >> p) & 1) o[x >> 3] |= 0x80 >> (x & 7); }
                else if (bpp == 8) o[x] = (unsigned char)c;
                else if (bpp == 2) o[x >> 2] |= (c & 3) << (6 - 2 * (x & 3));
                else if (c & 1) o[x >> 3] |= 0x80 >> (x & 7);
            }
            o += rowbytes;
        }
    }
}

void qb_gput(qb_i32 step, double x, double y, qbarr *a, qb_i32 off, qb_i32 action)
{
    qbscreen *s = &qb_scr;
    if (!need_gfx()) return;
    if (step) { x += s->lx; y += s->ly; }
    double px, py; log2phys(x, y, &px, &py);
    int ax = iround(px), ay = iround(py);
    if (!a->data) { qb_error(5); return; }
    unsigned char *base = (unsigned char *)a->data + (long)off * a->esz;
    qb_i16 hw, hh; memcpy(&hw, base, 2); memcpy(&hh, base + 2, 2);
    int bpp = bits_per_pixel_packed(), planes = s->planes > 1 ? s->planes : 1;
    int w = planes > 1 ? hw : hw / (bpp ? bpp : 1), h = hh;
    int rowbytes = (w * bpp + 7) / 8;
    if (w <= 0 || h <= 0) return;
    if (s->win && !s->win_screen) ay = ay - h + 1;   /* y-up WINDOW: point is the lower-left corner */
    if (ax < s->vx1 || ay < s->vy1 || ax + w - 1 > s->vx2 || ay + h - 1 > s->vy2) { qb_error(5); return; }
    long need = 4 + (long)rowbytes * planes * h;
    long avail = ((long)a->n - off) * a->esz;
    if (need > avail) { qb_error(5); return; }
    unsigned char *o = base + 4;
    int mask = s->ncolors - 1;
    for (int yy = 0; yy < h; yy++) {
        int rowc[2048];
        int ww = w > 2048 ? 2048 : w;
        for (int xx = 0; xx < ww; xx++) rowc[xx] = 0;
        for (int p = 0; p < planes; p++) {
            for (int xx = 0; xx < ww; xx++) {
                int v;
                if (planes > 1) v = ((o[xx >> 3] >> (7 - (xx & 7))) & 1) << p;
                else if (bpp == 8) v = o[xx];
                else if (bpp == 2) v = (o[xx >> 2] >> (6 - 2 * (xx & 3))) & 3;
                else v = (o[xx >> 3] >> (7 - (xx & 7))) & 1;
                rowc[xx] |= v;
            }
            o += rowbytes;
        }
        for (int xx = 0; xx < ww; xx++) {
            int X = ax + xx, Y = ay + yy;
            int d = getpix(X, Y); if (d < 0) continue;
            int sc = rowc[xx], r;
            switch (action) {
            case 1: r = sc; break;                 /* PSET */
            case 2: r = (~sc) & mask; break;       /* PRESET */
            case 3: r = d & sc; break;             /* AND */
            case 4: r = d | sc; break;             /* OR */
            default: r = d ^ sc; break;            /* XOR */
            }
            s->pix[s->apage][(size_t)Y * s->w + X] = (unsigned char)(r & mask);
        }
    }
    s->lx = x; s->ly = y;
    s->dirty = 1;
}
