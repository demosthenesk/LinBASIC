/* display_win.inc - Windows output backends, included by display.c:
 *   window:  a GDI window showing the emulated VGA screen (all SCREEN modes)
 *   console: the cmd.exe console (text modes), written with WriteConsoleOutputW
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */

static volatile int x_running, x_ready;
static char pending_title[256];
static volatile int title_changed;
static volatile int finished;

/* ---- Windows virtual keys -> QB key codes (same codes as the X11 backend) ---- */
static int vk_to_qb(int vk, unsigned ch, int shift, int ctrl, int alt)
{
    int st = 0; if (shift) st |= 3; if (ctrl) st |= 4; if (alt) st |= 8;
    shift_state = st;
    if (vk >= 0x70 && vk <= 0x79) {                /* F1..F10 */
        int f = vk - 0x70;
        if (shift) return 0x100 | (84 + f);
        if (ctrl) return 0x100 | (94 + f);
        if (alt) return 0x100 | (104 + f);
        return 0x100 | (59 + f);
    }
    switch (vk) {
    case 0x7A: return 0x100 | (shift ? 135 : ctrl ? 137 : alt ? 139 : 133);   /* F11 */
    case 0x7B: return 0x100 | (shift ? 136 : ctrl ? 138 : alt ? 140 : 134);   /* F12 */
    case 0x26: return 0x100 | (ctrl ? 141 : 72);     /* up    */
    case 0x28: return 0x100 | (ctrl ? 145 : 80);     /* down  */
    case 0x25: return 0x100 | (ctrl ? 115 : 75);     /* left  */
    case 0x27: return 0x100 | (ctrl ? 116 : 77);     /* right */
    case 0x24: return 0x100 | (ctrl ? 119 : 71);     /* home  */
    case 0x23: return 0x100 | (ctrl ? 117 : 79);     /* end   */
    case 0x21: return 0x100 | (ctrl ? 132 : 73);     /* pgup  */
    case 0x22: return 0x100 | (ctrl ? 118 : 81);     /* pgdn  */
    case 0x2D: return 0x100 | 82;                    /* ins   */
    case 0x2E: return 0x100 | 83;                    /* del   */
    case 0x0C: return 0x100 | 76;                    /* keypad 5 */
    case 0x09: return shift ? 0x100 | 15 : 9;
    case 0x0D: return ctrl ? 10 : 13;
    case 0x1B: return 27;
    case 0x08: return ctrl ? 127 : 8;
    case 0x13: case 0x03:                            /* Pause / Ctrl+Break */
        if (ctrl) { qb_break_flag = 1; return -2; }
        return -1;
    case 0x10: case 0x11: case 0x12: case 0x14: case 0x90: case 0x91:
    case 0x5B: case 0x5C: case 0x5D: case 0xA0: case 0xA1: case 0xA2: case 0xA3: case 0xA4: case 0xA5:
        return -1;
    }
    if (alt && !ctrl && vk >= 'A' && vk <= 'Z') {
        static const unsigned char sc[26] = { 30, 48, 46, 32, 18, 33, 34, 35, 23, 36, 37, 38, 50, 49, 24, 25, 16, 19, 31, 20, 22, 47, 17, 45, 21, 44 };
        return 0x100 | sc[vk - 'A'];
    }
    if (alt && !ctrl && vk >= '0' && vk <= '9') return 0x100 | (vk == '0' ? 129 : 120 + (vk - '1'));
    if (ch) {
        if (ctrl && ch == 3 && (qb_rt_flags & 2)) { qb_break_flag = 1; return -2; }
        if (ch < 128) return ch;
        for (int i = 128; i < 256; i++) if (cp437_uni[i] == ch) return i;
    }
    return -1;
}

static int have_desktop(void) { return 1; }

static int stdin_byte(void)
{
    static int in_eof;
    if (in_eof) return -1;
    int a = qbw_stdin_available();
    if (a < 0) { in_eof = 1; return -1; }
    if (a == 0) return -1;
    unsigned char ch;
    if (_read(0, &ch, 1) != 1) { in_eof = 1; return -1; }
    if (ch == '\r') return stdin_byte();
    return ch;
}

/* ================================================================== */
/* GDI window                                                          */
static HWND hwnd;
static int win_w, win_h;
static uint32_t *gframe;
static size_t gframe_cap;
static pthread_t xthread;

static void gdi_present(void)
{
    if (!hwnd || win_w < 16 || win_h < 16) return;
    size_t need = (size_t)win_w * win_h;
    if (need > gframe_cap) { free(gframe); gframe = malloc(need * 4); gframe_cap = gframe ? need : 0; if (!gframe) return; }
    scale_frame(gframe, win_w, win_w, win_h);
    BITMAPINFO bi;
    memset(&bi, 0, sizeof bi);
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = win_w;
    bi.bmiHeader.biHeight = -win_h;              /* top-down */
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    bi.bmiHeader.biCompression = BI_RGB;
    HDC dc = GetDC(hwnd);
    SetDIBitsToDevice(dc, 0, 0, win_w, win_h, 0, 0, 0, win_h, gframe, &bi, DIB_RGB_COLORS);
    ReleaseDC(hwnd, dc);
}

static void set_window_title(HWND h, const char *t)
{
    WCHAR w[300];
    if (MultiByteToWideChar(CP_ACP, 0, t, -1, w, 300) > 0) SetWindowTextW(h, w);
}

static void mouse_at(int mx, int my)
{
    extern int qb_mouse_x, qb_mouse_y;
    int dw = win_w, dh = win_w * 3 / 4; if (dh > win_h) { dh = win_h; dw = win_h * 4 / 3; }
    if (dw <= 0 || dh <= 0) return;
    int ox = (win_w - dw) / 2, oy = (win_h - dh) / 2;
    double fx = (double)(mx - ox) / dw, fy = (double)(my - oy) / dh;
    if (fx < 0) fx = 0; if (fx > 0.999) fx = 0.999; if (fy < 0) fy = 0; if (fy > 0.999) fy = 0.999;
    if (qb_scr.text) { qb_mouse_x = (int)(fx * qb_scr.cols) * 8 * (qb_scr.cols == 40 ? 2 : 1); qb_mouse_y = (int)(fy * qb_scr.rows) * 8; }
    else { qb_mouse_x = (int)(fx * qb_scr.w) * (qb_scr.w == 320 ? 2 : 1); qb_mouse_y = (int)(fy * qb_scr.h); }
}

static void win_key(int k)
{
    if (k == -2) { quit_requested = 1; return; }
    if (k >= 0) { if (finished) quit_requested = 1; else key_from_device(k); }
}

static LRESULT CALLBACK wndproc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    extern int qb_mouse_b;
    switch (msg) {
    case WM_CLOSE: quit_requested = 1; return 0;
    case WM_ERASEBKGND: return 1;
    case WM_PAINT: { PAINTSTRUCT ps; BeginPaint(h, &ps); EndPaint(h, &ps); qb_scr.dirty = 1; return 0; }
    case WM_SIZE: win_w = LOWORD(lp); win_h = HIWORD(lp); qb_scr.dirty = 1; return 0;
    case WM_KEYDOWN: case WM_SYSKEYDOWN: {
        int shift = GetKeyState(VK_SHIFT) < 0, ctrl = GetKeyState(VK_CONTROL) < 0, alt = GetKeyState(VK_MENU) < 0;
        int k = vk_to_qb((int)wp, 0, shift, ctrl, alt);
        win_key(k);
        if (msg == WM_SYSKEYDOWN && wp == VK_F4 && alt) quit_requested = 1;
        return 0;
    }
    case WM_KEYUP: case WM_SYSKEYUP: {
        int st = 0;
        if (GetKeyState(VK_SHIFT) < 0) st |= 3; if (GetKeyState(VK_CONTROL) < 0) st |= 4; if (GetKeyState(VK_MENU) < 0) st |= 8;
        shift_state = st;
        return 0;
    }
    case WM_CHAR: {
        unsigned ch = (unsigned)wp;
        if (ch == 8 || ch == 9 || ch == 10 || ch == 13 || ch == 27 || ch == 127) return 0;   /* sent by WM_KEYDOWN */
        int ctrl = GetKeyState(VK_CONTROL) < 0, alt = GetKeyState(VK_MENU) < 0;
        win_key(vk_to_qb(0, ch, 0, ctrl && !alt, 0));
        return 0;
    }
    case WM_SYSCHAR: return 0;                       /* no beep for Alt+key */
    case WM_MOUSEMOVE: mouse_at((short)LOWORD(lp), (short)HIWORD(lp)); return 0;
    case WM_LBUTTONDOWN: SetCapture(h); qb_mouse_b |= 1; mouse_at((short)LOWORD(lp), (short)HIWORD(lp)); return 0;
    case WM_LBUTTONUP: ReleaseCapture(); qb_mouse_b &= ~1; return 0;
    case WM_RBUTTONDOWN: qb_mouse_b |= 2; return 0;
    case WM_RBUTTONUP: qb_mouse_b &= ~2; return 0;
    case WM_MBUTTONDOWN: qb_mouse_b |= 4; return 0;
    case WM_MBUTTONUP: qb_mouse_b &= ~4; return 0;
    }
    return DefWindowProcW(h, msg, wp, lp);
}

static void *x_thread_main(void *arg)
{
    (void)arg;
    HINSTANCE inst = GetModuleHandleW(NULL);
    WNDCLASSW wc;
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = wndproc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursorW(NULL, (LPCWSTR)IDC_ARROW);
    wc.hIcon = LoadIconW(inst, (LPCWSTR)(uintptr_t)1);
    if (!wc.hIcon) wc.hIcon = LoadIconW(NULL, (LPCWSTR)IDI_APPLICATION);
    wc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
    wc.lpszClassName = L"LinBASICScreen";
    RegisterClassW(&wc);
    int sh = GetSystemMetrics(SM_CYSCREEN);
    int H = 600;
    if (sh >= 1000) H = 800;
    if (sh >= 1400) H = 1050;
    const char *z = getenv("QB_WINDOW_HEIGHT");
    if (z && atoi(z) >= 200) H = atoi(z);
    RECT r = { 0, 0, H * 4 / 3, H };
    AdjustWindowRect(&r, WS_OVERLAPPEDWINDOW, FALSE);
    hwnd = CreateWindowW(L"LinBASICScreen", L"LinBASIC", WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT,
                         r.right - r.left, r.bottom - r.top, NULL, NULL, inst, NULL);
    if (!hwnd) { x_ready = -1; return NULL; }
    char title[160]; snprintf(title, sizeof title, "%s - LinBASIC", qb_module_name);
    set_window_title(hwnd, title);
    ShowWindow(hwnd, SW_SHOWNORMAL);
    UpdateWindow(hwnd);
    SetForegroundWindow(hwnd);
    x_running = 1;
    x_ready = 1;
    int last_mode_w = -1, last_mode_h = -1;
    double next_blink = qb_now() + 0.2667, next_cursor = qb_now() + 0.133;
    for (;;) {
        MSG m;
        while (PeekMessageW(&m, NULL, 0, 0, PM_REMOVE)) { TranslateMessage(&m); DispatchMessageW(&m); }
        if (quit_requested && !finished) {
            fflush(stdout);
            qbsnd_shutdown();
            qbf_close_all();
            _exit(0);
        }
        if (quit_requested && finished) {
            x_running = 0;
            pthread_mutex_lock(&kq_lock); pthread_cond_broadcast(&kq_cond); pthread_mutex_unlock(&kq_lock);
            DestroyWindow(hwnd);
            return NULL;
        }
        if (title_changed) { title_changed = 0; set_window_title(hwnd, pending_title); }
        double t = qb_now();
        if (t >= next_blink) { blink_phase ^= 1; next_blink = t + 0.2667; if (qb_scr.text) qb_scr.dirty = 1; }
        if (t >= next_cursor) { cursor_phase ^= 1; next_cursor = t + 0.133; if (qb_scr.cursor_on || qb_scr.input_cursor) qb_scr.dirty = 1; }
        if (qb_scr.w != last_mode_w || qb_scr.h != last_mode_h) { last_mode_w = qb_scr.w; last_mode_h = qb_scr.h; map_sw = 0; qb_scr.dirty = 1; }
        if (qb_scr.dirty) { qb_scr.dirty = 0; gdi_present(); }
        MsgWaitForMultipleObjects(0, NULL, FALSE, 15, QS_ALLINPUT);
        qb_poll_events();
    }
    return NULL;
}

static int x11_start(void)
{
    if (getenv("QB_NOWINDOW")) return 0;
    if (pthread_create(&xthread, NULL, x_thread_main, NULL) != 0) return 0;
    for (int i = 0; i < 500 && !x_ready; i++) Sleep(10);
    return x_ready == 1;
}

/* ================================================================== */
/* cmd.exe console                                                     */
static HANDLE hcin, hcout;
static DWORD in_mode0;
static int in_mode_saved;
static WORD con_attr0;
static int con_left, con_top;
static CHAR_INFO *cbuf;
static int cbuf_cells;
static pthread_t cthread;
static volatile int c_running;
static volatile int c_paused, c_pause_ack;
static volatile int con_full;

static void con_restore(void)
{
    if (in_mode_saved) { SetConsoleMode(hcin, in_mode0); in_mode_saved = 0; }
    CONSOLE_CURSOR_INFO ci;
    if (GetConsoleCursorInfo(hcout, &ci)) { ci.bVisible = TRUE; SetConsoleCursorInfo(hcout, &ci); }
    SetConsoleTextAttribute(hcout, con_attr0);
}

static void con_raw(void)
{
    if (GetConsoleMode(hcin, &in_mode0)) {
        in_mode_saved = 1;
        /* no line editing, echo or Ctrl+C processing: keys arrive one by one */
        SetConsoleMode(hcin, in_mode0 & ~(ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT | ENABLE_PROCESSED_INPUT));
    }
}

static void con_present(int full)
{
    (void)full;
    qbscreen *s = &qb_scr;
    uint16_t *t = s->txt[s->vpage];
    if (!t) return;
    int n = s->cols * s->rows;
    if (n > cbuf_cells) { free(cbuf); cbuf = malloc(sizeof(CHAR_INFO) * n); cbuf_cells = cbuf ? n : 0; if (!cbuf) return; }
    for (int i = 0; i < n; i++) {
        uint16_t v = t[i];
        int ch = v & 0xFF, a = v >> 8;
        if ((a & 0x80) && blink_phase) a = (a & 0x70) | ((a >> 4) & 7);   /* blink: show the background */
        cbuf[i].Char.UnicodeChar = ch == 0 ? L' ' : (WCHAR)cp437_uni[ch];
        cbuf[i].Attributes = (WORD)(a & 0x7F);
    }
    COORD size = { (SHORT)s->cols, (SHORT)s->rows }, origin = { 0, 0 };
    SMALL_RECT rg = { (SHORT)con_left, (SHORT)con_top, (SHORT)(con_left + s->cols - 1), (SHORT)(con_top + s->rows - 1) };
    WriteConsoleOutputW(hcout, cbuf, size, origin, &rg);
    int col = s->ccol >= s->cols ? s->cols - 1 : s->ccol;
    COORD cp = { (SHORT)(con_left + col), (SHORT)(con_top + s->crow) };
    SetConsoleCursorPosition(hcout, cp);
    CONSOLE_CURSOR_INFO ci;
    if (GetConsoleCursorInfo(hcout, &ci)) {
        BOOL show = (s->cursor_on || s->input_cursor) ? TRUE : FALSE;
        if (ci.bVisible != show) { ci.bVisible = show; SetConsoleCursorInfo(hcout, &ci); }
    }
}

static int con_read_key(int timeout_ms)
{
    if (WaitForSingleObject(hcin, timeout_ms) != WAIT_OBJECT_0) return -1;
    INPUT_RECORD ir; DWORD n = 0;
    if (!ReadConsoleInputW(hcin, &ir, 1, &n) || n == 0) return -1;
    if (ir.EventType == WINDOW_BUFFER_SIZE_EVENT) { con_full = 1; qb_scr.dirty = 1; return -1; }
    if (ir.EventType != KEY_EVENT || !ir.Event.KeyEvent.bKeyDown) {
        if (ir.EventType == KEY_EVENT) {
            DWORD cs = ir.Event.KeyEvent.dwControlKeyState; int st = 0;
            if (cs & SHIFT_PRESSED) st |= 3; if (cs & (LEFT_CTRL_PRESSED | RIGHT_CTRL_PRESSED)) st |= 4; if (cs & (LEFT_ALT_PRESSED | RIGHT_ALT_PRESSED)) st |= 8;
            shift_state = st;
        }
        return -1;
    }
    KEY_EVENT_RECORD *k = &ir.Event.KeyEvent;
    DWORD cs = k->dwControlKeyState;
    int shift = (cs & SHIFT_PRESSED) != 0, ctrl = (cs & (LEFT_CTRL_PRESSED | RIGHT_CTRL_PRESSED)) != 0, alt = (cs & (LEFT_ALT_PRESSED | RIGHT_ALT_PRESSED)) != 0;
    int key = vk_to_qb(k->wVirtualKeyCode, k->uChar.UnicodeChar, shift, ctrl && !(alt && k->uChar.UnicodeChar), alt && !(ctrl && k->uChar.UnicodeChar));
    for (int i = 1; key >= 0 && i < k->wRepeatCount; i++) key_from_device(key);
    return key;
}

static void *con_thread_main(void *arg)
{
    (void)arg;
    double next_blink = qb_now() + 0.2667;
    while (c_running) {
        if (c_paused) { c_pause_ack = 1; Sleep(10); continue; }
        c_pause_ack = 0;
        int k = con_read_key(15);
        if (k == -2 || (k == 3 && (qb_rt_flags & 2))) { con_restore(); _exit(0); }
        if (k >= 0) key_from_device(k);
        if (title_changed) { title_changed = 0; SetConsoleTitleA(pending_title); }
        double t = qb_now();
        if (t >= next_blink) { blink_phase ^= 1; next_blink = t + 0.2667; qb_scr.dirty = 1; }
        if (qb_scr.dirty) { qb_scr.dirty = 0; pthread_mutex_lock(&qb_scr_lock); con_present(con_full); con_full = 0; pthread_mutex_unlock(&qb_scr_lock); }
        qb_poll_events();
    }
    return NULL;
}

static BOOL WINAPI con_ctrl_handler(DWORD type)
{
    if (type == CTRL_BREAK_EVENT || type == CTRL_C_EVENT) {
        if (qb_rt_flags & 2) { con_restore(); fflush(stdout); _exit(0); }
        return TRUE;                                 /* ignored, as in a program compiled without /D */
    }
    con_restore();
    return FALSE;
}

static void con_start(void)
{
    hcout = GetStdHandle(STD_OUTPUT_HANDLE);
    hcin = GetStdHandle(STD_INPUT_HANDLE);
    CONSOLE_SCREEN_BUFFER_INFO bi;
    if (!GetConsoleScreenBufferInfo(hcout, &bi)) return;
    con_attr0 = bi.wAttributes;
    /* make room for an 80x25 screen */
    COORD bs = bi.dwSize;
    int need_w = qb_scr.cols > 80 ? qb_scr.cols : 80;
    if (bs.X < need_w) { bs.X = (SHORT)need_w; SetConsoleScreenBufferSize(hcout, bs); }
    GetConsoleScreenBufferInfo(hcout, &bi);
    if (bi.srWindow.Right - bi.srWindow.Left + 1 < need_w || bi.srWindow.Bottom - bi.srWindow.Top + 1 < 25) {
        SMALL_RECT w = { 0, bi.srWindow.Top, (SHORT)(need_w - 1), (SHORT)(bi.srWindow.Top + 24) };
        SetConsoleWindowInfo(hcout, TRUE, &w);
        GetConsoleScreenBufferInfo(hcout, &bi);
    }
    con_left = bi.srWindow.Left;
    con_top = bi.srWindow.Top;
    if (con_top + 25 > bi.dwSize.Y) con_top = bi.dwSize.Y - 25 < 0 ? 0 : bi.dwSize.Y - 25;
    /* clear the visible window, like CLS */
    DWORD wr;
    int vis_w = bi.srWindow.Right - bi.srWindow.Left + 1, vis_h = bi.srWindow.Bottom - bi.srWindow.Top + 1;
    for (int y = 0; y < vis_h; y++) {
        COORD c = { bi.srWindow.Left, (SHORT)(bi.srWindow.Top + y) };
        FillConsoleOutputCharacterW(hcout, L' ', vis_w, c, &wr);
        FillConsoleOutputAttribute(hcout, 7, vis_w, c, &wr);
    }
    con_raw();
    SetConsoleCtrlHandler(con_ctrl_handler, TRUE);
    char title[160]; snprintf(title, sizeof title, "%s - LinBASIC", qb_module_name);
    SetConsoleTitleA(title);
    atexit(con_restore);
    c_running = 1;
    pthread_create(&cthread, NULL, con_thread_main, NULL);
}

static void con_finish(void)
{
    COORD c = { 0, (SHORT)(con_top + qb_scr.rows - 1) };
    SetConsoleCursorPosition(hcout, c);
    con_restore();
    fputs("\n", stdout);
    fflush(stdout);
}

/* SHELL: hand the console to the child process and take it back afterwards */
void qbd_console_suspend(int on)
{
    if (qb_mode_display != QBD_CONSOLE) return;
    if (on) {
        c_paused = 1;
        for (int i = 0; i < 200 && !c_pause_ack; i++) Sleep(5);
        con_restore();
        COORD c = { 0, (SHORT)(con_top + qb_scr.crow) };
        SetConsoleCursorPosition(hcout, c);
    } else {
        con_raw();
        con_full = 1; qb_scr.dirty = 1;
        c_paused = 0;
    }
}

/* ================================================================== */
/* line mode: a terminal program in cmd.exe writes plain lines         */
static int line_raw_on, line_inited;
static DWORD line_in_mode0;
static UINT line_cp_out0, line_cp_in0;

static void line_raw(int on)
{
    if (on == line_raw_on || !line_inited) return;
    if (on) SetConsoleMode(hcin, line_in_mode0 & ~(ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT));   /* Ctrl+C still works */
    else SetConsoleMode(hcin, line_in_mode0);
    line_raw_on = on;
}

static void line_restore(void)
{
    if (!line_inited) return;
    fflush(stdout);
    line_raw(0);
    SetConsoleTextAttribute(hcout, con_attr0);
    if (line_cp_out0) SetConsoleOutputCP(line_cp_out0);
    if (line_cp_in0) SetConsoleCP(line_cp_in0);
}

static void line_start(void)
{
    hcout = GetStdHandle(STD_OUTPUT_HANDLE);
    hcin = GetStdHandle(STD_INPUT_HANDLE);
    CONSOLE_SCREEN_BUFFER_INFO bi;
    if (!GetConsoleScreenBufferInfo(hcout, &bi) || !GetConsoleMode(hcin, &line_in_mode0)) { qb_line_tty = 0; return; }
    con_attr0 = bi.wAttributes;
    line_cp_out0 = GetConsoleOutputCP();
    line_cp_in0 = GetConsoleCP();
    SetConsoleCP(437);                    /* typed characters arrive as CP437 bytes */
    line_inited = 1;
    atexit(line_restore);
}

static int line_key(int wait_ms) { fflush(stdout); line_raw(1); return con_read_key(wait_ms); }

/* characters 128-255 go to the console as Unicode, whatever its code page */
static void qbw_console_putc(int c)
{
    WCHAR w = (WCHAR)cp437_uni[c & 0xFF];
    DWORD wr;
    fflush(stdout);
    if (!WriteConsoleW(hcout, &w, 1, &wr, NULL)) fputc(c, stdout);
}

void qbd_line_color(int fg, int bg)
{
    if (!line_inited) return;
    fflush(stdout);
    int f = fg & 15, b = bg & 7;
    SetConsoleTextAttribute(hcout, (f == 7 && b == 0) ? con_attr0 : (WORD)((b << 4) | f));
}

void qbd_line_cls(void)
{
    if (!line_inited) return;
    fflush(stdout);
    CONSOLE_SCREEN_BUFFER_INFO bi;
    if (!GetConsoleScreenBufferInfo(hcout, &bi)) return;
    DWORD n = (DWORD)bi.dwSize.X * bi.dwSize.Y, wr;
    COORD home = { 0, 0 };
    FillConsoleOutputCharacterW(hcout, L' ', n, home, &wr);
    FillConsoleOutputAttribute(hcout, bi.wAttributes, n, home, &wr);
    SetConsoleCursorPosition(hcout, home);
}
