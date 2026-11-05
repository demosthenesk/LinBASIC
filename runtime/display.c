/* display.c - output backends: X11 window (loaded at run time), ANSI console,
 * headless (for tests) and plain stream (stdout redirected).
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */
#include "qbrt_int.h"
#ifndef _WIN32
#include <dlfcn.h>
#include <unistd.h>
#include <poll.h>
#include <termios.h>
#include <signal.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#include <X11/extensions/XShm.h>
#include <sys/ipc.h>
#include <sys/shm.h>
#endif
#include "cp437.h"

int qb_mode_display = QBD_STREAM;
int qb_line_tty;
#ifdef _WIN32
static void qbw_console_putc(int c);        /* CP437 character -> Unicode console output */
#endif

/* ------------------------------------------------------------------ */
/* key queue                                                           */
static pthread_mutex_t kq_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t kq_cond = PTHREAD_COND_INITIALIZER;
static int kq[256], kq_head, kq_tail;
static volatile int shift_state;
static volatile int quit_requested;

void qbd_key_push(int k)
{
    pthread_mutex_lock(&kq_lock);
    int nt = (kq_tail + 1) & 255;
    if (nt != kq_head) { kq[kq_tail] = k; kq_tail = nt; }
    pthread_cond_signal(&kq_cond);
    pthread_mutex_unlock(&kq_lock);
}
static void key_from_device(int k)
{
    if (qb_ev_key_trapped(k)) return;
    qbd_key_push(k);
}
int qbd_shift_state(void) { return shift_state; }

/* ------------------------------------------------------------------ */
/* rendering of the emulated screen into a 32-bit RGB image            */
static int blink_phase, cursor_phase;

void qbd_render_rgb(uint32_t *out, int *pw, int *ph, int maxw, int maxh)
{
    qbscreen *s = &qb_scr;
    int w = s->w, h = s->h;
    if (w > maxw) w = maxw;
    if (h > maxh) h = maxh;
    *pw = w; *ph = h;
    int vp = s->vpage;
    if (s->text) {
        uint16_t *t = s->txt[vp];
        if (!t) return;
        const unsigned char *font = s->font;
        int cw = s->cw, ch = s->ch;
        for (int r = 0; r < s->rows; r++) for (int c = 0; c < s->cols; c++) {
            uint16_t cell = t[r * s->cols + c];
            int code = cell & 0xFF, attr = cell >> 8;
            uint32_t fg = s->pal[attr & 15], bg = s->pal[(attr >> 4) & 7];
            int blink = (attr & 0x80) && !blink_phase;
            const unsigned char *g = font + code * ch;
            for (int y = 0; y < ch; y++) {
                int yy = r * ch + y; if (yy >= h) break;
                uint32_t *row = out + (size_t)yy * w + c * cw;
                unsigned bits = blink ? 0 : g[y];
                for (int x = 0; x < 8; x++) row[x] = (bits & (0x80 >> x)) ? fg : bg;
                if (cw == 9) row[8] = (code >= 0xC0 && code <= 0xDF && (bits & 1)) ? fg : bg;
            }
        }
    } else {
        unsigned char *p = s->pix[vp];
        if (!p) return;
        for (int y = 0; y < h; y++) {
            unsigned char *src = p + (size_t)y * s->w;
            uint32_t *row = out + (size_t)y * w;
            for (int x = 0; x < w; x++) row[x] = s->pal[src[x]];
        }
    }
    /* cursor */
    int show = (s->cursor_on || s->input_cursor) && cursor_phase && s->vpage == s->apage;
    if (show && s->crow < s->rows) {
        int c = s->ccol >= s->cols ? s->cols - 1 : s->ccol;
        int ch = s->ch, cw = s->cw;
        uint32_t col = s->text ? s->pal[(s->txt[vp][s->crow * s->cols + c] >> 8) & 15] : s->pal[s->fg & (s->ncolors - 1)];
        for (int y = ch - 2; y < ch; y++) {
            int yy = s->crow * ch + y; if (yy >= h) break;
            for (int x = 0; x < cw && c * cw + x < w; x++) out[(size_t)yy * w + c * cw + x] = col;
        }
    }
}

void qbd_screenshot(const char *path)
{
    static uint32_t buf[800 * 600];
    int w, h;
    qbd_render_rgb(buf, &w, &h, 800, 600);
    FILE *f = fopen(path, "wb");
    if (!f) return;
    fprintf(f, "P6\n%d %d\n255\n", w, h);
    for (int i = 0; i < w * h; i++) { unsigned char px[3] = { buf[i] >> 16, buf[i] >> 8, buf[i] }; fwrite(px, 1, 3, f); }
    fclose(f);
}

/* ------------------------------------------------------------------ */
/* the emulated screen scaled into a window: 4:3, centred, sharp-bilinear */
static uint32_t *base;          /* emulated-screen buffer */
/* sharp-bilinear scaling tables */
static int *mapx0, *mapx1, *wx, *mapy0, *mapy1, *wy;
static int map_sw, map_sh, map_dw, map_dh;
static void build_map(int sw, int sh, int dw, int dh)
{
    if (sw == map_sw && sh == map_sh && dw == map_dw && dh == map_dh) return;
    free(mapx0); free(mapx1); free(wx); free(mapy0); free(mapy1); free(wy);
    mapx0 = malloc(sizeof(int) * dw); mapx1 = malloc(sizeof(int) * dw); wx = malloc(sizeof(int) * dw);
    mapy0 = malloc(sizeof(int) * dh); mapy1 = malloc(sizeof(int) * dh); wy = malloc(sizeof(int) * dh);
    double sx = (double)dw / sw, sy = (double)dh / sh;
    for (int x = 0; x < dw; x++) {
        double u = (x + 0.5) / sx - 0.5; int i = (int)floor(u); double f = u - i;
        double g = (f - 0.5) * sx + 0.5; if (g < 0) g = 0; if (g > 1) g = 1;
        if (i < 0) { i = 0; g = 0; } if (i >= sw - 1) { i = sw - 1; g = 0; }
        mapx0[x] = i; mapx1[x] = i + (i < sw - 1); wx[x] = (int)(g * 256);
    }
    for (int y = 0; y < dh; y++) {
        double u = (y + 0.5) / sy - 0.5; int i = (int)floor(u); double f = u - i;
        double g = (f - 0.5) * sy + 0.5; if (g < 0) g = 0; if (g > 1) g = 1;
        if (i < 0) { i = 0; g = 0; } if (i >= sh - 1) { i = sh - 1; g = 0; }
        mapy0[y] = i; mapy1[y] = i + (i < sh - 1); wy[y] = (int)(g * 256);
    }
    map_sw = sw; map_sh = sh; map_dw = dw; map_dh = dh;
}
static inline uint32_t mix(uint32_t a, uint32_t b, int w)
{
    if (w <= 0) return a; if (w >= 256) return b;
    uint32_t rb = ((a & 0xFF00FF) * (256 - w) + (b & 0xFF00FF) * w) >> 8;
    uint32_t g = ((a & 0x00FF00) * (256 - w) + (b & 0x00FF00) * w) >> 8;
    return (rb & 0xFF00FF) | (g & 0x00FF00);
}

static uint32_t *hrow;
static int hrow_cap;
static void scale_frame(uint32_t *frame, int stride, int win_w, int win_h)
{
    int sw, sh;
    if (!base) base = malloc(sizeof(uint32_t) * 720 * 480);
    pthread_mutex_lock(&qb_scr_lock);
    qbd_render_rgb(base, &sw, &sh, 720, 480);
    pthread_mutex_unlock(&qb_scr_lock);
    /* fit 4:3 inside the window */
    int dw = win_w, dh = win_w * 3 / 4;
    if (dh > win_h) { dh = win_h; dw = win_h * 4 / 3; }
    if (dw < 16 || dh < 16) return;
    int ox = (win_w - dw) / 2, oy = (win_h - dh) / 2;
    build_map(sw, sh, dw, dh);
    if (hrow_cap < dw * 2) { hrow_cap = dw * 2; hrow = realloc(hrow, sizeof(uint32_t) * hrow_cap); }
    int last0 = -1, last1 = -1;
    uint32_t *r0 = hrow, *r1 = hrow + dw;
    for (int y = 0; y < dh; y++) {
        int a = mapy0[y], b = mapy1[y];
        if (a != last0) {
            if (a == last1) { uint32_t *t = r0; r0 = r1; r1 = t; last0 = a; last1 = -1; }
            else { uint32_t *src = base + (size_t)a * sw; for (int x = 0; x < dw; x++) r0[x] = mix(src[mapx0[x]], src[mapx1[x]], wx[x]); last0 = a; }
        }
        if (b != last1) {
            uint32_t *src = base + (size_t)b * sw; for (int x = 0; x < dw; x++) r1[x] = mix(src[mapx0[x]], src[mapx1[x]], wx[x]); last1 = b;
        }
        uint32_t *dst = frame + (size_t)(y + oy) * stride + ox;
        int w = wy[y];
        if (w == 0) memcpy(dst, r0, dw * 4);
        else for (int x = 0; x < dw; x++) dst[x] = mix(r0[x], r1[x], w);
    }
    /* borders */
    if (ox > 0 || oy > 0) {
        for (int y = 0; y < win_h; y++) {
            uint32_t *row = frame + (size_t)y * stride;
            if (y < oy || y >= oy + dh) memset(row, 0, win_w * 4);
            else { memset(row, 0, ox * 4); memset(row + ox + dw, 0, (win_w - ox - dw) * 4); }
        }
    }
}

static void utf8_put(FILE *f, unsigned c)
{
    if (c < 0x80) fputc(c, f);
    else if (c < 0x800) { fputc(0xC0 | (c >> 6), f); fputc(0x80 | (c & 63), f); }
    else { fputc(0xE0 | (c >> 12), f); fputc(0x80 | ((c >> 6) & 63), f); fputc(0x80 | (c & 63), f); }
}

#ifndef _WIN32
/* ------------------------------------------------------------------ */
/* X11 backend (libX11 is loaded with dlopen so programs run without it) */
#define XF(ret, name, args) static ret (*p##name) args;
XF(Display *, XOpenDisplay, (const char *))
XF(int, XCloseDisplay, (Display *))
XF(Window, XCreateSimpleWindow, (Display *, Window, int, int, unsigned, unsigned, unsigned, unsigned long, unsigned long))
XF(int, XStoreName, (Display *, Window, const char *))
XF(int, XSelectInput, (Display *, Window, long))
XF(int, XMapWindow, (Display *, Window))
XF(GC, XCreateGC, (Display *, Drawable, unsigned long, XGCValues *))
XF(XImage *, XCreateImage, (Display *, Visual *, unsigned, int, int, char *, unsigned, unsigned, int, int))
XF(int, XPutImage, (Display *, Drawable, GC, XImage *, int, int, int, int, unsigned, unsigned))
XF(int, XFlush, (Display *))
XF(int, XPending, (Display *))
XF(int, XNextEvent, (Display *, XEvent *))
XF(int, XLookupString, (XKeyEvent *, char *, int, KeySym *, XComposeStatus *))
XF(Atom, XInternAtom, (Display *, const char *, Bool))
XF(Status, XSetWMProtocols, (Display *, Window, Atom *, int))
XF(int, XResizeWindow, (Display *, Window, unsigned, unsigned))
XF(int, XFillRectangle, (Display *, Drawable, GC, int, int, unsigned, unsigned))
XF(int, XSetForeground, (Display *, GC, unsigned long))
XF(XSizeHints *, XAllocSizeHints, (void))
XF(void, XSetWMNormalHints, (Display *, Window, XSizeHints *))
XF(int, XFree, (void *))
XF(int, XSync, (Display *, Bool))
XF(XClassHint *, XAllocClassHint, (void))
XF(int, XSetClassHint, (Display *, Window, XClassHint *))
XF(int, XChangeProperty, (Display *, Window, Atom, Atom, int, int, const unsigned char *, int))
XF(Bool, XShmQueryExtension, (Display *))
XF(XImage *, XShmCreateImage, (Display *, Visual *, unsigned, int, char *, XShmSegmentInfo *, unsigned, unsigned))
XF(Bool, XShmAttach, (Display *, XShmSegmentInfo *))
XF(Bool, XShmDetach, (Display *, XShmSegmentInfo *))
XF(Bool, XShmPutImage, (Display *, Drawable, GC, XImage *, int, int, int, int, unsigned, unsigned, Bool))
XF(int, XSetErrorHandler, (void *))

static Display *dpy;
static Window win;
static GC gc;
static Atom wm_delete;
static int win_w, win_h;
static XImage *ximg;
static XShmSegmentInfo shminfo;
static int use_shm;
static uint32_t *frame;         /* window-size buffer */
static pthread_t xthread;
static volatile int x_running, x_ready;
static volatile int want_resize_mode;
static char pending_title[256];
static volatile int title_changed;
static volatile int finished;

static int load_x11(void)
{
    void *h = dlopen("libX11.so.6", RTLD_NOW | RTLD_GLOBAL);
    if (!h) return 0;
#define L(name) if (!(p##name = dlsym(h, #name))) return 0;
    L(XOpenDisplay) L(XCloseDisplay) L(XCreateSimpleWindow) L(XStoreName) L(XSelectInput) L(XMapWindow)
    L(XCreateGC) L(XCreateImage) L(XPutImage) L(XFlush) L(XPending) L(XNextEvent) L(XLookupString)
    L(XInternAtom) L(XSetWMProtocols) L(XResizeWindow) L(XFillRectangle) L(XSetForeground)
    L(XAllocSizeHints) L(XSetWMNormalHints) L(XFree) L(XSync) L(XAllocClassHint) L(XSetClassHint) L(XChangeProperty)
    L(XSetErrorHandler)
#undef L
    void *e = dlopen("libXext.so.6", RTLD_NOW);
    if (e) {
        pXShmQueryExtension = dlsym(e, "XShmQueryExtension");
        pXShmCreateImage = dlsym(e, "XShmCreateImage");
        pXShmAttach = dlsym(e, "XShmAttach");
        pXShmDetach = dlsym(e, "XShmDetach");
        pXShmPutImage = dlsym(e, "XShmPutImage");
    }
    return 1;
}

/* display geometry: logical screen is shown with a 4:3 aspect */
static void mode_window_size(int *w, int *h)
{
    int sh = 0;
    if (dpy) sh = DisplayHeight(dpy, DefaultScreen(dpy));
    int H = 600;
    if (sh >= 1000) H = 800;
    if (sh >= 1400) H = 1050;
    const char *z = getenv("QB_WINDOW_HEIGHT");
    if (z && atoi(z) >= 200) H = atoi(z);
    *h = H; *w = H * 4 / 3;
}

static void destroy_image(void)
{
    if (!ximg) return;
    if (use_shm) { pXShmDetach(dpy, &shminfo); ximg->data = NULL; XDestroyImage(ximg); shmdt(shminfo.shmaddr); shmctl(shminfo.shmid, IPC_RMID, 0); }
    else { ximg->data = NULL; XDestroyImage(ximg); free(frame); }
    ximg = NULL; frame = NULL;
}

static int shm_failed;
static int xerr_handler(Display *d, XErrorEvent *e) { (void)d; (void)e; shm_failed = 1; return 0; }

static void create_image(int w, int h)
{
    destroy_image();
    Visual *vis = DefaultVisual(dpy, DefaultScreen(dpy));
    int depth = DefaultDepth(dpy, DefaultScreen(dpy));
    use_shm = 0;
    if (pXShmQueryExtension && pXShmQueryExtension(dpy) && !getenv("QB_NOSHM")) {
        ximg = pXShmCreateImage(dpy, vis, depth, ZPixmap, NULL, &shminfo, w, h);
        if (ximg) {
            shminfo.shmid = shmget(IPC_PRIVATE, (size_t)ximg->bytes_per_line * h, IPC_CREAT | 0600);
            if (shminfo.shmid >= 0) {
                shminfo.shmaddr = ximg->data = shmat(shminfo.shmid, 0, 0);
                shminfo.readOnly = False;
                shm_failed = 0;
                pXSetErrorHandler(xerr_handler);
                pXShmAttach(dpy, &shminfo);
                pXSync(dpy, False);
                if (!shm_failed) { use_shm = 1; frame = (uint32_t *)ximg->data; return; }
                shmdt(shminfo.shmaddr); shmctl(shminfo.shmid, IPC_RMID, 0);
            }
            ximg->data = NULL; XDestroyImage(ximg); ximg = NULL;
        }
    }
    frame = malloc((size_t)w * h * 4);
    ximg = pXCreateImage(dpy, vis, depth, ZPixmap, 0, (char *)frame, w, h, 32, w * 4);
}


static void present(void)
{
    if (!ximg) return;
    scale_frame(frame, ximg->bytes_per_line / 4, win_w, win_h);
    if (use_shm) pXShmPutImage(dpy, win, gc, ximg, 0, 0, 0, 0, win_w, win_h, False);
    else pXPutImage(dpy, win, gc, ximg, 0, 0, 0, 0, win_w, win_h);
    pXFlush(dpy);
}

static int xkey_to_qb(XKeyEvent *ev)
{
    char buf[8]; KeySym ks = 0;
    int n = pXLookupString(ev, buf, sizeof buf, &ks, NULL);
    int shift = ev->state & ShiftMask, ctrl = ev->state & ControlMask, alt = ev->state & Mod1Mask;
    int st = 0; if (shift) st |= 3; if (ctrl) st |= 4; if (alt) st |= 8;
    shift_state = st;
    switch (ks) {
    case XK_F1: case XK_F2: case XK_F3: case XK_F4: case XK_F5: case XK_F6: case XK_F7: case XK_F8: case XK_F9: case XK_F10: {
        int f = ks - XK_F1;
        if (shift) return 0x100 | (84 + f);
        if (ctrl) return 0x100 | (94 + f);
        if (alt) return 0x100 | (104 + f);
        return 0x100 | (59 + f);
    }
    case XK_F11: return 0x100 | (shift ? 135 : ctrl ? 137 : alt ? 139 : 133);
    case XK_F12: return 0x100 | (shift ? 136 : ctrl ? 138 : alt ? 140 : 134);
    case XK_Up: case XK_KP_Up: return 0x100 | (ctrl ? 141 : 72);
    case XK_Down: case XK_KP_Down: return 0x100 | (ctrl ? 145 : 80);
    case XK_Left: case XK_KP_Left: return 0x100 | (ctrl ? 115 : 75);
    case XK_Right: case XK_KP_Right: return 0x100 | (ctrl ? 116 : 77);
    case XK_Home: case XK_KP_Home: return 0x100 | (ctrl ? 119 : 71);
    case XK_End: case XK_KP_End: return 0x100 | (ctrl ? 117 : 79);
    case XK_Prior: case XK_KP_Prior: return 0x100 | (ctrl ? 132 : 73);
    case XK_Next: case XK_KP_Next: return 0x100 | (ctrl ? 118 : 81);
    case XK_Insert: case XK_KP_Insert: return 0x100 | 82;
    case XK_Delete: case XK_KP_Delete: return 0x100 | 83;
    case XK_KP_Begin: return 0x100 | 76;
    case XK_ISO_Left_Tab: return 0x100 | 15;
    case XK_Tab: if (shift) return 0x100 | 15; return 9;
    case XK_Return: case XK_KP_Enter: return ctrl ? 10 : 13;
    case XK_Escape: return 27;
    case XK_BackSpace: return ctrl ? 127 : 8;
    case XK_Pause: case XK_Break: if (ctrl) { qb_break_flag = 1; return -2; } return -1;
    case XK_Shift_L: case XK_Shift_R: case XK_Control_L: case XK_Control_R: case XK_Alt_L: case XK_Alt_R:
    case XK_Caps_Lock: case XK_Num_Lock: case XK_Super_L: case XK_Super_R: case XK_Meta_L: case XK_Meta_R: return -1;
    }
    if (alt && ks >= XK_a && ks <= XK_z) {
        static const unsigned char sc[26] = { 30, 48, 46, 32, 18, 33, 34, 35, 23, 36, 37, 38, 50, 49, 24, 25, 16, 19, 31, 20, 22, 47, 17, 45, 21, 44 };
        return 0x100 | sc[ks - XK_a];
    }
    if (alt && ks >= XK_0 && ks <= XK_9) { return 0x100 | (ks == XK_0 ? 129 : 120 + (ks - XK_1)); }
    if (n == 1) {
        unsigned char c = (unsigned char)buf[0];
        if (ctrl && c == 3 && (qb_rt_flags & 2)) { qb_break_flag = 1; return -2; }
        return c;
    }
    /* non-ASCII keysyms (e.g. Greek letters) -> try CP437 */
    if (ks >= 0x100 && ks < 0x10000) {
        unsigned int uni = 0;
        if (ks >= 0x7a1 && ks <= 0x7f9) {   /* Greek keysyms: map via Latin-1 fallback none */
            uni = 0;
        }
        (void)uni;
    }
    return -1;
}

static void *x_thread_main(void *arg)
{
    (void)arg;
    int last_mode_w = -1, last_mode_h = -1;
    double next_blink = qb_now() + 0.2667, next_cursor = qb_now() + 0.133;
    for (;;) {
        while (pXPending(dpy)) {
            XEvent ev; pXNextEvent(dpy, &ev);
            switch (ev.type) {
            case Expose: qb_scr.dirty = 1; break;
            case ConfigureNotify:
                if (ev.xconfigure.width != win_w || ev.xconfigure.height != win_h) {
                    win_w = ev.xconfigure.width; win_h = ev.xconfigure.height;
                    create_image(win_w, win_h); qb_scr.dirty = 1;
                }
                break;
            case KeyPress: {
                int k = xkey_to_qb(&ev.xkey);
                if (k == -2) { quit_requested = 1; break; }
                if (k >= 0) { if (finished) quit_requested = 1; else key_from_device(k); }
                break;
            }
            case KeyRelease: {
                int st = 0; unsigned m = ev.xkey.state;
                KeySym ks = 0; char b[4]; pXLookupString(&ev.xkey, b, 4, &ks, NULL);
                if (m & ShiftMask) st |= 3; if (m & ControlMask) st |= 4; if (m & Mod1Mask) st |= 8;
                if (ks == XK_Shift_L || ks == XK_Shift_R) st &= ~3;
                if (ks == XK_Control_L || ks == XK_Control_R) st &= ~4;
                if (ks == XK_Alt_L || ks == XK_Alt_R) st &= ~8;
                shift_state = st;
                break;
            }
            case ButtonPress: case ButtonRelease: case MotionNotify: {
                extern int qb_mouse_x, qb_mouse_y, qb_mouse_b;
                int mx = ev.type == MotionNotify ? ev.xmotion.x : ev.xbutton.x, my = ev.type == MotionNotify ? ev.xmotion.y : ev.xbutton.y;
                int dw = win_w, dh = win_w * 3 / 4; if (dh > win_h) { dh = win_h; dw = win_h * 4 / 3; }
                int ox = (win_w - dw) / 2, oy = (win_h - dh) / 2;
                double fx = (double)(mx - ox) / dw, fy = (double)(my - oy) / dh;
                if (fx < 0) fx = 0; if (fx > 0.999) fx = 0.999; if (fy < 0) fy = 0; if (fy > 0.999) fy = 0.999;
                if (qb_scr.text) { qb_mouse_x = (int)(fx * qb_scr.cols) * 8 * (qb_scr.cols == 40 ? 2 : 1); qb_mouse_y = (int)(fy * qb_scr.rows) * 8; }
                else { qb_mouse_x = (int)(fx * qb_scr.w) * (qb_scr.w == 320 ? 2 : 1); qb_mouse_y = (int)(fy * qb_scr.h); }
                if (ev.type == ButtonPress || ev.type == ButtonRelease) {
                    int bit = ev.xbutton.button == 1 ? 1 : ev.xbutton.button == 3 ? 2 : ev.xbutton.button == 2 ? 4 : 0;
                    if (ev.type == ButtonPress) qb_mouse_b |= bit; else qb_mouse_b &= ~bit;
                }
                break;
            }
            case ClientMessage:
                if ((Atom)ev.xclient.data.l[0] == wm_delete) quit_requested = 1;
                break;
            }
        }
        if (quit_requested && !finished) {
            /* window closed / Ctrl+Break: terminate the program */
            fflush(stdout);
            qbsnd_shutdown();
            qbf_close_all();
            _exit(0);
        }
        if (quit_requested && finished) { x_running = 0; pthread_mutex_lock(&kq_lock); pthread_cond_broadcast(&kq_cond); pthread_mutex_unlock(&kq_lock); return NULL; }
        if (title_changed) { title_changed = 0; pXStoreName(dpy, win, pending_title); }
        double t = qb_now();
        if (t >= next_blink) { blink_phase ^= 1; next_blink = t + 0.2667; if (qb_scr.text) qb_scr.dirty = 1; }
        if (t >= next_cursor) { cursor_phase ^= 1; next_cursor = t + 0.133; if (qb_scr.cursor_on || qb_scr.input_cursor) qb_scr.dirty = 1; }
        if (qb_scr.w != last_mode_w || qb_scr.h != last_mode_h) { last_mode_w = qb_scr.w; last_mode_h = qb_scr.h; map_sw = 0; qb_scr.dirty = 1; }
        if (qb_scr.dirty) { qb_scr.dirty = 0; present(); }
        struct pollfd pfd = { ConnectionNumber(dpy), POLLIN, 0 };
        poll(&pfd, 1, 15);
        qb_poll_events();
    }
    return NULL;
}

static int x11_start(void)
{
    if (!getenv("DISPLAY")) return 0;
    if (!load_x11()) return 0;
    dpy = pXOpenDisplay(NULL);
    if (!dpy) return 0;
    int scr = DefaultScreen(dpy);
    mode_window_size(&win_w, &win_h);
    win = pXCreateSimpleWindow(dpy, RootWindow(dpy, scr), 0, 0, win_w, win_h, 0, BlackPixel(dpy, scr), BlackPixel(dpy, scr));
    char title[160]; snprintf(title, sizeof title, "%s - LinBASIC", qb_module_name);
    pXStoreName(dpy, win, title);
    XClassHint *ch = pXAllocClassHint();
    if (ch) { ch->res_name = "linbasic-program"; ch->res_class = "LinBASIC"; pXSetClassHint(dpy, win, ch); pXFree(ch); }
    XSizeHints *sh = pXAllocSizeHints();
    if (sh) { sh->flags = PMinSize; sh->min_width = 320; sh->min_height = 240; pXSetWMNormalHints(dpy, win, sh); pXFree(sh); }
    pXSelectInput(dpy, win, ExposureMask | KeyPressMask | KeyReleaseMask | StructureNotifyMask | ButtonPressMask | ButtonReleaseMask | PointerMotionMask);
    wm_delete = pXInternAtom(dpy, "WM_DELETE_WINDOW", False);
    pXSetWMProtocols(dpy, win, &wm_delete, 1);
    gc = pXCreateGC(dpy, win, 0, NULL);
    create_image(win_w, win_h);
    pXMapWindow(dpy, win);
    pXFlush(dpy);
    x_running = 1;
    pthread_create(&xthread, NULL, x_thread_main, NULL);
    return 1;
}

/* ------------------------------------------------------------------ */
/* ANSI console backend                                                */
static struct termios saved_tio;
static int tio_saved;
static uint16_t *con_shadow;
static int con_cols, con_rows;
static pthread_t cthread;
static volatile int c_running;

static void con_restore(void)
{
    if (tio_saved) { tcsetattr(0, TCSANOW, &saved_tio); tio_saved = 0; }
    fputs("\033[0m\033[?25h", stdout); fflush(stdout);
}


static void con_present(int full)
{
    qbscreen *s = &qb_scr;
    uint16_t *t = s->txt[s->vpage];
    if (!t) return;
    if (con_cols != s->cols || con_rows != s->rows) {
        free(con_shadow); con_cols = s->cols; con_rows = s->rows;
        con_shadow = malloc(sizeof(uint16_t) * con_cols * con_rows); full = 1;
        fputs("\033[2J", stdout);
    }
    static const int ansi[8] = { 0, 4, 2, 6, 1, 5, 3, 7 };
    int lastattr = -1;
    for (int r = 0; r < s->rows; r++) {
        int need_move = 1;
        for (int c = 0; c < s->cols; c++) {
            uint16_t v = t[r * s->cols + c];
            if (!full && con_shadow[r * s->cols + c] == v) { need_move = 1; continue; }
            con_shadow[r * s->cols + c] = v;
            if (need_move) { printf("\033[%d;%dH", r + 1, c + 1); need_move = 0; }
            int a = v >> 8;
            if (a != lastattr) {
                int fg = a & 15, bg = (a >> 4) & 7;
                printf("\033[0;%d;%d%sm", fg == 7 ? 39 : fg >= 8 ? 90 + ansi[fg & 7] : 30 + ansi[fg],
                       bg == 0 ? 49 : 40 + ansi[bg], (a & 0x80) ? ";5" : "");
                lastattr = a;
            }
            int ch = v & 0xFF;
            utf8_put(stdout, ch == 0 ? ' ' : cp437_uni[ch]);
        }
    }
    int show = s->cursor_on || s->input_cursor;
    printf("\033[%d;%dH%s", s->crow + 1, (s->ccol >= s->cols ? s->cols - 1 : s->ccol) + 1, show ? "\033[?25h" : "\033[?25l");
    fflush(stdout);
}

static int con_read_key(int timeout_ms)
{
    struct pollfd p = { 0, POLLIN, 0 };
    if (poll(&p, 1, timeout_ms) <= 0) return -1;
    unsigned char b[16]; int n = read(0, b, sizeof b);
    if (n <= 0) return -1;
    if (b[0] == 27 && n == 1) return 27;
    if (b[0] == 27 && n >= 3 && (b[1] == '[' || b[1] == 'O')) {
        char seq[16] = {0}; memcpy(seq, b + 2, n - 2 < 14 ? n - 2 : 14);
        switch (seq[0]) {
        case 'A': return 0x100 | 72; case 'B': return 0x100 | 80; case 'C': return 0x100 | 77; case 'D': return 0x100 | 75;
        case 'H': return 0x100 | 71; case 'F': return 0x100 | 79;
        case 'P': return 0x100 | 59; case 'Q': return 0x100 | 60; case 'R': return 0x100 | 61; case 'S': return 0x100 | 62;
        }
        int num = atoi(seq);
        switch (num) {
        case 1: return 0x100 | 71; case 2: return 0x100 | 82; case 3: return 0x100 | 83; case 4: return 0x100 | 79;
        case 5: return 0x100 | 73; case 6: return 0x100 | 81;
        case 15: return 0x100 | 63; case 17: return 0x100 | 64; case 18: return 0x100 | 65; case 19: return 0x100 | 66;
        case 20: return 0x100 | 67; case 21: return 0x100 | 68; case 23: return 0x100 | 133; case 24: return 0x100 | 134;
        }
        return -1;
    }
    if (b[0] == 127) return 8;
    if (b[0] == 10) return 13;
    if (b[0] >= 0xC0 && n >= 2) {
        /* UTF-8 -> CP437 */
        unsigned u = b[0] >= 0xE0 && n >= 3 ? ((b[0] & 15) << 12) | ((b[1] & 63) << 6) | (b[2] & 63) : ((b[0] & 31) << 6) | (b[1] & 63);
        for (int i = 128; i < 256; i++) if (cp437_uni[i] == u) return i;
        return -1;
    }
    return b[0];
}

static void *con_thread_main(void *arg)
{
    (void)arg;
    while (c_running) {
        int k = con_read_key(15);
        if (k >= 0) { if (k == 3 && (qb_rt_flags & 2)) { con_restore(); _exit(0); } key_from_device(k); }
        if (qb_scr.dirty) { qb_scr.dirty = 0; pthread_mutex_lock(&qb_scr_lock); con_present(0); pthread_mutex_unlock(&qb_scr_lock); }
        qb_poll_events();
    }
    return NULL;
}

static void con_start(void)
{
    if (tcgetattr(0, &saved_tio) == 0) {
        struct termios t = saved_tio;
        t.c_lflag &= ~(ICANON | ECHO | ISIG);
        t.c_iflag &= ~(IXON | ICRNL);
        t.c_cc[VMIN] = 0; t.c_cc[VTIME] = 0;
        tcsetattr(0, TCSANOW, &t);
        tio_saved = 1;
    }
    fputs("\033[?25l\033[2J", stdout);
    atexit(con_restore);
    c_running = 1;
    pthread_create(&cthread, NULL, con_thread_main, NULL);
}

static void con_finish(void)
{
    printf("\033[0m\033[%d;1H\n", qb_scr.rows);
    con_restore();
}
void qbd_console_suspend(int on) { (void)on; }
static int have_desktop(void) { return getenv("DISPLAY") != NULL; }
static int stdin_byte(void)
{
    static int in_eof;
    struct pollfd p = { 0, POLLIN, 0 };
    if (!in_eof && poll(&p, 1, 0) > 0) {
        unsigned char ch;
        ssize_t r = read(0, &ch, 1);
        if (r == 1) return ch;
        in_eof = 1;
    }
    return -1;
}
/* line mode (terminal program on a terminal): keys without Enter, colours as SGR */
static int line_raw_on, line_colored;
static void line_raw(int on)
{
    if (on == line_raw_on) return;
    if (on) {
        if (!tio_saved && tcgetattr(0, &saved_tio) == 0) tio_saved = 1;
        if (tio_saved) {
            struct termios t = saved_tio;
            t.c_lflag &= ~(ICANON | ECHO);          /* ISIG stays: Ctrl+C ends the program */
            t.c_cc[VMIN] = 0; t.c_cc[VTIME] = 0;
            tcsetattr(0, TCSANOW, &t);
        }
    } else if (tio_saved) tcsetattr(0, TCSANOW, &saved_tio);
    line_raw_on = on;
}
static void line_restore(void)
{
    line_raw(0);
    if (line_colored) { fputs("\033[0m", stdout); line_colored = 0; }
    fflush(stdout);
}
static void line_signal(int sig)
{
    /* Ctrl+C or kill: give the terminal back before ending like any other command */
    if (tio_saved) tcsetattr(0, TCSANOW, &saved_tio);
    if (line_colored) { ssize_t r = write(1, "\033[0m", 4); (void)r; }
    signal(sig, SIG_DFL);
    raise(sig);
}
static void line_start(void)
{
    atexit(line_restore);
    signal(SIGINT, line_signal);
    signal(SIGTERM, line_signal);
    signal(SIGQUIT, line_signal);
    signal(SIGHUP, line_signal);
}
static int line_key(int wait_ms) { fflush(stdout); line_raw(1); return con_read_key(wait_ms); }
void qbd_line_color(int fg, int bg)
{
    static const int ansi[8] = { 0, 4, 2, 6, 1, 5, 3, 7 };
    char sgr[48];
    int f = fg & 15, b = bg & 7;
    snprintf(sgr, sizeof sgr, "\033[0;%d;%d%sm",
             f == 7 ? 39 : f >= 8 ? 90 + ansi[f & 7] : 30 + ansi[f],
             b == 0 ? 49 : 40 + ansi[b], (fg & 16) ? ";5" : "");
    fputs(sgr, stdout);
    line_colored = !(f == 7 && b == 0 && !(fg & 16));
}
void qbd_line_cls(void) { fputs("\033[H\033[2J", stdout); fflush(stdout); }
#else
#include "display_win.inc"
#endif

void qbd_console_write(const char *s, int n) { (void)s; (void)n; }

/* stream mode: characters go to stdout, CP437 graphics converted to UTF-8 */
void qbd_stream_putc(int c)
{
    static int raw = -1;
    if (raw < 0) raw = getenv("QB_RAW") != NULL;
#ifdef _WIN32
    if (qb_line_tty && c >= 128) { qbw_console_putc(c); return; }
#endif
    if (raw || c < 128 || c == 0) fputc(c, stdout);
    else utf8_put(stdout, cp437_uni[c & 0xFF]);
}

/* ------------------------------------------------------------------ */
/* headless: keys from QB_KEYS                                         */
static const char *hl_keys;
static void headless_feed(void)
{
    if (!hl_keys) return;
    while (*hl_keys) {
        if (*hl_keys == '{') {
            const char *e = strchr(hl_keys, '}');
            if (e) {
                char name[16] = {0}; int l = e - hl_keys - 1; if (l > 15) l = 15; memcpy(name, hl_keys + 1, l);
                int k = -1;
                if (!strcasecmp(name, "ENTER")) k = 13; else if (!strcasecmp(name, "ESC")) k = 27;
                else if (!strcasecmp(name, "UP")) k = 0x100 | 72; else if (!strcasecmp(name, "DOWN")) k = 0x100 | 80;
                else if (!strcasecmp(name, "LEFT")) k = 0x100 | 75; else if (!strcasecmp(name, "RIGHT")) k = 0x100 | 77;
                else if (!strcasecmp(name, "BS")) k = 8; else if (!strcasecmp(name, "TAB")) k = 9;
                else if ((name[0] == 'F' || name[0] == 'f') && atoi(name + 1) >= 1 && atoi(name + 1) <= 10) k = 0x100 | (58 + atoi(name + 1));
                hl_keys = e + 1;
                if (k >= 0) { key_from_device(k); return; }
                continue;
            }
        }
        key_from_device((unsigned char)*hl_keys++);
        return;
    }
}

/* test helper: QB_EXIT_AFTER=seconds takes a screenshot (QB_SCREENSHOT) and exits */
static void *watchdog_main(void *arg)
{
    double secs = *(double *)arg;
    qb_msleep((int)(secs * 1000));
    const char *shot = getenv("QB_SCREENSHOT");
    pthread_mutex_lock(&qb_scr_lock);
    if (shot && *shot) qbd_screenshot(shot);
    pthread_mutex_unlock(&qb_scr_lock);
    fflush(stdout);
    _exit(0);
    return NULL;
}

/* ------------------------------------------------------------------ */
void qbd_init(void)
{
    const char *m = getenv("QB_DISPLAY");
    int want = -1;
    if (m) {
        if (!strcasecmp(m, "window")) want = QBD_WINDOW;
        else if (!strcasecmp(m, "console")) want = QBD_CONSOLE;
        else if (!strcasecmp(m, "stream")) want = QBD_STREAM;
        else if (!strcasecmp(m, "headless")) want = QBD_HEADLESS;
    }
    if (want < 0) {
        if (qb_rt_flags & 4) want = QBD_STREAM;            /* compiled as a terminal program */
        else if (have_desktop()) want = QBD_WINDOW;
        else if (isatty(1) && isatty(0)) want = QBD_CONSOLE;
        else want = QBD_STREAM;
    }
    if (want == QBD_WINDOW && !x11_start()) want = isatty(1) ? QBD_CONSOLE : QBD_STREAM;
    if (want == QBD_CONSOLE && !isatty(1)) want = QBD_STREAM;
    qb_mode_display = want;
    if (want == QBD_STREAM && (qb_rt_flags & 4) && !m && isatty(1) && isatty(0)) { qb_line_tty = 1; line_start(); }
    if (want == QBD_CONSOLE) con_start();
    if (want == QBD_HEADLESS) hl_keys = getenv("QB_KEYS");
    const char *ea = getenv("QB_EXIT_AFTER");
    if (ea && atof(ea) > 0) { static pthread_t wd; static double secs; secs = atof(ea); pthread_create(&wd, NULL, watchdog_main, &secs); }
}

int qbd_has_window(void) { return qb_mode_display == QBD_WINDOW; }

void qbd_line_cooked(void) { if (qb_line_tty) { fflush(stdout); line_raw(0); } }

/* LOCATE, VIEW PRINT ...: a terminal program becomes a full-screen text program */
void qbd_need_screen(void)
{
    if (!qb_line_tty) return;
    line_restore();
    qb_line_tty = 0;
    qb_mode_display = QBD_CONSOLE;
    qbs_cls_region(0, qb_scr.rows - 1);
    qb_scr.crow = qb_scr.vtop; qb_scr.ccol = 0;
    con_start();
}

void qbd_mode_changed(void)
{
    qb_scr.dirty = 1;
    /* a console program that switches to a graphics mode continues in a window */
    if (qb_line_tty && !qb_scr.text && have_desktop() && !getenv("QB_NOWINDOW")) {
        line_restore();
        if (x11_start()) { qb_line_tty = 0; qb_mode_display = QBD_WINDOW; }
        return;
    }
    if (qb_mode_display == QBD_CONSOLE && !qb_scr.text && have_desktop() && !getenv("QB_NOWINDOW")) {
        c_running = 0;
        pthread_join(cthread, NULL);
        con_finish();
        if (x11_start()) qb_mode_display = QBD_WINDOW;
        else con_start();
    }
}
void qbd_dirty(void) { qb_scr.dirty = 1; }
void qbd_flush(void)
{
    qb_scr.dirty = 1;
    if (qb_mode_display == QBD_STREAM) fflush(stdout);
}
void qbd_set_title(const char *t) { snprintf(pending_title, sizeof pending_title, "%s", t); title_changed = 1; }

int qbd_getkey(int wait_ms)
{
    if (qb_mode_display == QBD_HEADLESS) {
        pthread_mutex_lock(&kq_lock); int empty = kq_head == kq_tail; pthread_mutex_unlock(&kq_lock);
        if (empty) headless_feed();
        qb_poll_events();
    }
    if (qb_break_flag && qb_mode_display != QBD_WINDOW) { qbd_shutdown(0); _exit(0); }
    if (qb_line_tty) {
        pthread_mutex_lock(&kq_lock);
        int k = -1;
        if (kq_head != kq_tail) { k = kq[kq_head]; kq_head = (kq_head + 1) & 255; }
        pthread_mutex_unlock(&kq_lock);
        if (k >= 0) return k;
        k = line_key(wait_ms > 0 ? wait_ms : 0);
        qb_poll_events();
        if (k >= 0 && qb_ev_key_trapped(k)) return -1;
        return k;
    }
    if (qb_mode_display == QBD_STREAM && wait_ms == 0) {
        /* redirected/piped stdin: INKEY$ reads what is available without blocking */
        int ch = stdin_byte();
        if (ch >= 0) return ch == '\n' ? 13 : ch;
    }
    pthread_mutex_lock(&kq_lock);
    if (kq_head == kq_tail && wait_ms > 0 && (qb_mode_display == QBD_WINDOW || qb_mode_display == QBD_CONSOLE)) {
        struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
        ts.tv_nsec += (long)wait_ms * 1000000L; ts.tv_sec += ts.tv_nsec / 1000000000L; ts.tv_nsec %= 1000000000L;
        pthread_cond_timedwait(&kq_cond, &kq_lock, &ts);
    }
    int k = -1;
    if (kq_head != kq_tail) { k = kq[kq_head]; kq_head = (kq_head + 1) & 255; }
    pthread_mutex_unlock(&kq_lock);
    return k;
}

void qbd_shutdown(int wait_key)
{
    static int done;
    if (done) return;
    done = 1;
    const char *shot = getenv("QB_SCREENSHOT");
    if (shot && *shot) qbd_screenshot(shot);
    fflush(stdout);
    if (qb_line_tty) line_restore();
    if (qb_mode_display == QBD_WINDOW && x_running) {
        if (wait_key && !getenv("QB_NOWAIT")) {
            char t[200]; snprintf(t, sizeof t, "%s - LinBASIC  [finished: press any key to close]", qb_module_name);
            qbd_set_title(t);
            qb_scr.dirty = 1;
            /* drop keys typed before the end */
            pthread_mutex_lock(&kq_lock); kq_head = kq_tail; pthread_mutex_unlock(&kq_lock);
            finished = 1;
            while (x_running) {
                pthread_mutex_lock(&kq_lock);
                if (kq_head != kq_tail) { pthread_mutex_unlock(&kq_lock); break; }
                struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts); ts.tv_sec += 1;
                pthread_cond_timedwait(&kq_cond, &kq_lock, &ts);
                pthread_mutex_unlock(&kq_lock);
            }
        }
        return;
    }
    if (qb_mode_display == QBD_CONSOLE) {
        c_running = 0;
        pthread_join(cthread, NULL);
        pthread_mutex_lock(&qb_scr_lock); con_present(0); pthread_mutex_unlock(&qb_scr_lock);
        con_finish();
    }
}
