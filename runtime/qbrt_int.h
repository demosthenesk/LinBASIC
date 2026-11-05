/* qbrt_int.h - internal declarations shared by the runtime modules.
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */
#ifndef QBRT_INT_H
#define QBRT_INT_H
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#ifdef _WIN32
#include "compat_win.h"
#else
#include <pthread.h>
#endif
#define QBRT_INTERNAL
#include "qbrt.h"

#define QB_MAXPAGES 8

typedef struct qbscreen {
    int mode;               /* SCREEN mode number                       */
    int text;               /* 1 = text mode (SCREEN 0)                 */
    int w, h;               /* pixel size of the graphics page          */
    int cols, rows;         /* text grid                                */
    int cw, ch;             /* character cell size in pixels            */
    int ncolors;            /* number of attributes                     */
    int bits;               /* bits per pixel used for GET/PUT          */
    int planes;             /* planes used for GET/PUT                  */
    int npages, apage, vpage;
    unsigned char *pix[QB_MAXPAGES];
    uint16_t *txt[QB_MAXPAGES];   /* char | attr << 8                */
    int fg, bg;             /* current attributes                       */
    int crow, ccol;         /* cursor, 0-based                          */
    int vtop, vbot;         /* VIEW PRINT rows, 0-based inclusive       */
    int cursor_on;          /* LOCATE ,,1                               */
    int cur_start, cur_stop;
    int input_cursor;       /* cursor shown while INPUT waits           */
    uint32_t pal[256];      /* attribute -> 0xRRGGBB                    */
    int egapal[16];         /* attribute -> EGA/CGA colour number       */
    int keyline;            /* KEY ON line shown                        */
    /* graphics state */
    double lx, ly;          /* last point (logical coordinates)         */
    int vx1, vy1, vx2, vy2; /* viewport (physical)                      */
    int view_screen;        /* VIEW SCREEN: coordinates absolute        */
    int win;                /* WINDOW active                            */
    int win_screen;
    double wx1, wy1, wx2, wy2;
    double draw_angle, draw_scale;
    int draw_ta;
    double draw_tav;
    int fontsize;
    const unsigned char *font;
    int border;
    int cga_pal, cga_bg;    /* SCREEN 1 palette / background            */
    volatile int dirty;
    int width_override;
} qbscreen;

extern qbscreen qb_scr;
extern pthread_mutex_t qb_scr_lock;
extern const unsigned char qb_font_08[2048], qb_font_14[3584], qb_font_16[4096];
extern const unsigned char qb_vga_default_pal[768];
extern char qb_module_name[64];
extern int qb_rt_flags;
extern int qb_mode_display;   /* 0 headless, 1 window, 2 console, 3 stream */

enum { QBD_HEADLESS = 0, QBD_WINDOW = 1, QBD_CONSOLE = 2, QBD_STREAM = 3 };

/* display.c */
void qbd_init(void);
void qbd_shutdown(int wait_key);
void qbd_mode_changed(void);
void qbd_dirty(void);
int qbd_getkey(int wait_ms);         /* -1 none; else ascii or 0x100|scan */
void qbd_flush(void);
int qbd_has_window(void);
void qbd_set_title(const char *t);
int qbd_shift_state(void);
void qbd_key_push(int k);
void qbd_render_rgb(uint32_t *out, int *w, int *h, int maxw, int maxh);
void qbd_screenshot(const char *path);
void qbd_console_write(const char *s, int n);
void qbd_console_suspend(int on);
/* terminal programs: plain lines on a terminal until a full-screen command is used */
extern int qb_line_tty;
void qbd_line_color(int fg, int bg);    /* COLOR in line mode            */
void qbd_line_cls(void);                /* CLS in line mode              */
void qbd_line_cooked(void);             /* before INPUT: normal line editing */
void qbd_need_screen(void);             /* LOCATE etc.: switch to the full text screen */       /* SHELL: give the console back to the child */

/* screen.c */
void qbs_init(void);
void qbs_putc(int c);
void qbs_write(const char *s, int n);
void qbs_newline(void);
void qbs_scroll(void);
void qbs_draw_char(int row, int col, int c, int fg, int bg);
void qbs_set_text_cell(int row, int col, int c, int attr);
int qbs_text_width(void);
void qbs_cursor_blink_reset(void);
void qbs_reset_palette(void);
uint32_t qbs_ega_rgb(int c);
void qbs_gfx_text_cell(int row, int col, int c, int fg, int bg);
void qbs_text_scroll_region(int top, int bot);
void qbs_cls_region(int top, int bot);

/* print.c */
void qb_fmt_single(float v, char *out);
void qb_fmt_double(double v, char *out);
int qb_parse_number(const char *s, int n, double *out, int *used);
qbs qb_input_line_screen(qbs prompt, int flags);

/* file.c */
typedef struct qbfile qbfile;
qbfile *qbf_get(int n, int needmode);
int qbf_getc(int n);
int qbf_eof_raw(int n);
void qbf_write(int n, const char *s, int len);
int qbf_col(int n);
int qbf_width(int n);
void qbf_close_all(void);
FILE *qb_fopen_ci(const char *name, const char *mode, char *resolved, int rsize);
void qb_path_from_dos(const char *in, char *out, int size);

/* sound.c */
void qbsnd_init(void);
void qbsnd_shutdown(void);
void qbsnd_tone(double freq, double ms, int wait);
void qbsnd_speaker(int on, double freq);
int qbsnd_queue_notes(void);
void qbsnd_wait_idle(void);

/* mem.c */
void qbm_init(void);
extern int qb_vretrace_hz;

/* core.c */
char *qb_cstr(qbs s);            /* temp NUL-terminated copy */
double qb_now(void);             /* monotonic seconds        */
void qb_msleep(int ms);
void qb_poll_events(void);
void qb_ev_key_trap(int key);
int qb_ev_key_trapped(int key);
extern int qb_break_flag;

#define QB_CLAMP(v, a, b) ((v) < (a) ? (a) : (v) > (b) ? (b) : (v))
#endif
