/* sound.c - BEEP, SOUND, PLAY and the PC speaker, played through PulseAudio
 * (libpulse-simple is loaded at run time; without it timing is still emulated).
 * Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later. */
#include "qbrt_int.h"
#include <ctype.h>
#ifndef _WIN32
#include <dlfcn.h>
#include <pulse/simple.h>
#endif

#define RATE 44100
typedef struct { double freq, ms; } seg;

static pthread_mutex_t q_lock = PTHREAD_MUTEX_INITIALIZER;
static seg queue[1024];
static int q_head, q_tail;
static double busy_until;          /* virtual clock: when queued sound ends */
static int notes_pending;
static volatile int spk_on;
static volatile double spk_freq;
static pthread_t athread;
static volatile int a_running;
#ifdef _WIN32
/* ---- Windows: waveOut (winmm.dll), a ring of short buffers --------------- */
typedef struct { void *lpData; DWORD dwBufferLength, dwBytesRecorded; DWORD_PTR dwUser; DWORD dwFlags, dwLoops; void *lpNext; DWORD_PTR reserved; } qbw_wavehdr;
typedef struct { WORD wFormatTag, nChannels; DWORD nSamplesPerSec, nAvgBytesPerSec; WORD nBlockAlign, wBitsPerSample, cbSize; } qbw_waveformat;
__declspec(dllimport) UINT __stdcall waveOutOpen(void **, UINT, const qbw_waveformat *, DWORD_PTR, DWORD_PTR, DWORD);
__declspec(dllimport) UINT __stdcall waveOutPrepareHeader(void *, qbw_wavehdr *, UINT);
__declspec(dllimport) UINT __stdcall waveOutUnprepareHeader(void *, qbw_wavehdr *, UINT);
__declspec(dllimport) UINT __stdcall waveOutWrite(void *, qbw_wavehdr *, UINT);
__declspec(dllimport) UINT __stdcall waveOutReset(void *);
__declspec(dllimport) UINT __stdcall waveOutClose(void *);
#define NBUF 4
static void *stream;              /* HWAVEOUT */
static qbw_wavehdr hdr[NBUF];
static short wbuf[NBUF][441];
static int wnext;
static int snd_open(void)
{
    qbw_waveformat f = { 1 /* PCM */, 1, RATE, RATE * 2, 2, 16, 0 };
    if (waveOutOpen(&stream, (UINT)-1 /* WAVE_MAPPER */, &f, 0, 0, 0) != 0) { stream = NULL; return 0; }
    for (int i = 0; i < NBUF; i++) { hdr[i].lpData = wbuf[i]; hdr[i].dwBufferLength = sizeof wbuf[i]; hdr[i].dwFlags = 0; waveOutPrepareHeader(stream, &hdr[i], sizeof hdr[i]); hdr[i].dwFlags |= 1 /* WHDR_DONE */; }
    return 1;
}
static int snd_write(const short *buf, int bytes)
{
    qbw_wavehdr *h = &hdr[wnext];
    while (!(h->dwFlags & 1) && a_running) Sleep(1);   /* wait until this buffer has been played */
    memcpy(wbuf[wnext], buf, bytes);
    h->dwBufferLength = bytes; h->dwFlags &= ~1;
    waveOutWrite(stream, h, sizeof *h);
    wnext = (wnext + 1) % NBUF;
    return 0;
}
static void snd_close(void)
{
    waveOutReset(stream);
    for (int i = 0; i < NBUF; i++) waveOutUnprepareHeader(stream, &hdr[i], sizeof hdr[i]);
    waveOutClose(stream);
}
#else
/* ---- Linux: PulseAudio (libpulse-simple loaded at run time) ------------- */
static void *pa;
static pa_simple *(*p_new)(const char *, const char *, pa_stream_direction_t, const char *, const char *, const pa_sample_spec *, const pa_channel_map *, const pa_buffer_attr *, int *);
static int (*p_write)(pa_simple *, const void *, size_t, int *);
static void (*p_free)(pa_simple *);
static int (*p_drain)(pa_simple *, int *);
static pa_simple *stream;
static int snd_open(void)
{
    pa = dlopen("libpulse-simple.so.0", RTLD_NOW);
    if (!pa) return 0;
    p_new = dlsym(pa, "pa_simple_new"); p_write = dlsym(pa, "pa_simple_write");
    p_free = dlsym(pa, "pa_simple_free"); p_drain = dlsym(pa, "pa_simple_drain");
    if (!p_new || !p_write || !p_free) return 0;
    pa_sample_spec ss = { PA_SAMPLE_S16LE, RATE, 1 };
    pa_buffer_attr at = { (uint32_t)-1, 4410 * 2, (uint32_t)-1, (uint32_t)-1, (uint32_t)-1 };
    int err;
    stream = p_new(NULL, "LinBASIC", PA_STREAM_PLAYBACK, NULL, "BASIC sound", &ss, NULL, &at, &err);
    return stream != NULL;
}
static int snd_write(const short *buf, int bytes) { int err; return p_write(stream, buf, bytes, &err); }
static void snd_close(void) { p_free(stream); }
#endif
static double cur_freq, cur_left;  /* ms left of current segment */
static double phase;
static int volume = 6000;

static void *audio_main(void *arg)
{
    (void)arg;
    short buf[441];
    while (a_running) {
        int active = 0;
        pthread_mutex_lock(&q_lock);
        if (cur_left <= 0 && q_head != q_tail) { cur_freq = queue[q_head].freq; cur_left = queue[q_head].ms; q_head = (q_head + 1) & 1023; if (notes_pending > 0) notes_pending--; }
        double f = 0;
        if (cur_left > 0) { active = 1; f = cur_freq; cur_left -= 10; }
        else if (spk_on) { active = 1; f = spk_freq; }
        pthread_mutex_unlock(&q_lock);
        if (!active) { qb_msleep(5); continue; }
        for (int i = 0; i < 441; i++) {
            short v = 0;
            if (f >= 37 && f < 20000) { phase += f / RATE; if (phase >= 1) phase -= floor(phase); v = phase < 0.5 ? volume : -volume; }
            buf[i] = v;
        }
        if (snd_write(buf, sizeof buf) < 0) qb_msleep(10);
    }
    return NULL;
}

void qbsnd_init(void)
{
    if (getenv("QB_NOSOUND")) return;
    if (qb_mode_display == QBD_HEADLESS) return;
}

static int ensure_audio(void)
{
    static int tried;
    if (stream) return 1;
    if (tried) return 0;
    tried = 1;
    if (getenv("QB_NOSOUND") || qb_mode_display == QBD_HEADLESS) return 0;
    if (!snd_open()) return 0;
    a_running = 1;
    pthread_create(&athread, NULL, audio_main, NULL);
    return 1;
}

void qbsnd_shutdown(void)
{
    if (a_running) { a_running = 0; pthread_join(athread, NULL); }
    if (stream) { snd_close(); stream = NULL; }
}

static void wait_until(double t)
{
    qbd_flush();
    while (qb_now() < t) {
        double d = t - qb_now();
        qb_msleep(d > 0.02 ? 20 : (int)(d * 1000) + 1);
        if (qb_evflag) break;
    }
}

int qbsnd_queue_notes(void)
{
    pthread_mutex_lock(&q_lock);
    double now = qb_now();
    if (busy_until < now) notes_pending = 0;
    int n = notes_pending;
    pthread_mutex_unlock(&q_lock);
    return n;
}

void qbsnd_wait_idle(void) { if (busy_until > qb_now()) wait_until(busy_until); }

static void enqueue(double freq, double ms, int is_note)
{
    ensure_audio();
    pthread_mutex_lock(&q_lock);
    double now = qb_now();
    if (busy_until < now) busy_until = now;
    busy_until += ms / 1000.0;
    if (is_note) notes_pending++;
    int nt = (q_tail + 1) & 1023;
    if (stream && nt != q_head) { queue[q_tail].freq = freq; queue[q_tail].ms = ms; q_tail = nt; }
    pthread_mutex_unlock(&q_lock);
}

void qbsnd_tone(double freq, double ms, int wait)
{
    if (wait) wait_until(busy_until);
    enqueue(freq, ms, 0);
}

void qbsnd_speaker(int on, double freq)
{
    if (on) ensure_audio();
    spk_freq = freq; spk_on = on;
}

void qb_beep(void)
{
    if (qb_mode_display == QBD_STREAM) { fputc(7, stdout); fflush(stdout); }
    wait_until(busy_until);
    enqueue(800, 250, 0);
    wait_until(busy_until);
}

void qb_sound(double freq, double dur)
{
    if (dur < 0 || dur > 65535 || ((freq < 37 || freq > 32767) && dur != 0)) { qb_error(5); return; }
    if (dur == 0) {
        pthread_mutex_lock(&q_lock); q_head = q_tail; cur_left = 0; busy_until = qb_now(); pthread_mutex_unlock(&q_lock);
        return;
    }
    double ms = dur * 1000.0 / 18.2065;
    /* QB: wait for the previous sound to finish, then start this one */
    wait_until(busy_until);
    enqueue(freq >= 32767 ? 0 : freq, ms, 0);
    /* very short sounds still take one clock tick */
}

/* ---- PLAY ---------------------------------------------------------------- */
static int pl_oct = 4, pl_len = 4, pl_tempo = 120, pl_mode = 0 /* 0 normal,1 legato,2 staccato */, pl_bg = 0;
static const char *pp; static int pn;

static int ppeek(void) { while (pn > 0 && (*pp == ' ' || *pp == ';')) { pp++; pn--; } return pn > 0 ? toupper((unsigned char)*pp) : -1; }
static int pget(void) { int c = ppeek(); if (c >= 0) { pp++; pn--; } return c; }
static int pnum(int *out)
{
    if (ppeek() == '=') {
        pget();
        if (pn >= 9 && pp[0] == 1) { double d; memcpy(&d, pp + 1, 8); pp += 9; pn -= 9; *out = (int)d; return 1; }
        return 0;
    }
    int any = 0, v = 0;
    while (pn > 0 && isdigit((unsigned char)*pp)) { v = v * 10 + (*pp - '0'); pp++; pn--; any = 1; }
    if (any) *out = v;
    return any;
}

static void play_note(int note /* 0..83 or -1 pause */, int len, int dots)
{
    double whole = 240000.0 / pl_tempo;   /* ms of a whole note: 4 beats */
    double ms = whole / len;
    double ext = ms;
    for (int i = 0; i < dots; i++) { ext /= 2; ms += ext; }
    if (note < 0) { enqueue(0, ms, 1); return; }
    double freq = 440.0 * pow(2.0, (note - 45) / 12.0);    /* O3 A (note 45) = 440 Hz; octave 3 starts at middle C */
    double on = pl_mode == 1 ? ms : pl_mode == 2 ? ms * 0.75 : ms * 0.875;
    enqueue(freq, on, 1);
    if (ms - on > 0.5) enqueue(0, ms - on, 0);
}

static void play_exec(const char *s, int n, int depth)
{
    const char *sp = pp; int sn = pn;
    pp = s; pn = n;
    static const int base[7] = { 9, 11, 0, 2, 4, 5, 7 };   /* A B C D E F G */
    while (depth < 10) {
        int c = pget();
        if (c < 0) break;
        int v;
        if (c >= 'A' && c <= 'G') {
            int note = base[c - 'A'] + pl_oct * 12;
            int d = ppeek();
            if (d == '#' || d == '+') { pget(); note++; } else if (d == '-') { pget(); note--; }
            int len = pl_len; if (pnum(&v) && v >= 1 && v <= 64) len = v;
            int dots = 0; while (ppeek() == '.') { pget(); dots++; }
            play_note(note, len, dots);
        } else switch (c) {
        case 'O': if (pnum(&v) && v >= 0 && v <= 6) pl_oct = v; break;
        case '>': if (pl_oct < 6) pl_oct++; break;
        case '<': if (pl_oct > 0) pl_oct--; break;
        case 'L': if (pnum(&v) && v >= 1 && v <= 64) pl_len = v; break;
        case 'T': if (pnum(&v) && v >= 32 && v <= 255) pl_tempo = v; break;
        case 'P': { int len = 4; if (pnum(&v) && v >= 1 && v <= 64) len = v; int dots = 0; while (ppeek() == '.') { pget(); dots++; } play_note(-1, len, dots); break; }
        case 'N': if (pnum(&v)) { int dots = 0; while (ppeek() == '.') { pget(); dots++; } play_note(v == 0 ? -1 : v - 1, pl_len, dots); } break;
        case 'M': {
            int m = pget();
            if (m == 'N') pl_mode = 0; else if (m == 'L') pl_mode = 1; else if (m == 'S') pl_mode = 2;
            else if (m == 'F') pl_bg = 0; else if (m == 'B') pl_bg = 1;
            break;
        }
        case 'X':
            if (pn >= 5 && pp[0] == 2) {
                int l; memcpy(&l, pp + 1, 4); const char *sub = pp + 5; pp += 5 + l; pn -= 5 + l;
                const char *rp = pp; int rn = pn; play_exec(sub, l, depth + 1); pp = rp; pn = rn;
            }
            break;
        default: break;
        }
    }
    pp = sp; pn = sn;
}

void qb_play(qbs music)
{
    play_exec(music.p, music.len, 0);
    if (!pl_bg) wait_until(busy_until);
    else {
        /* background buffer holds 32 notes: wait while it is full */
        while (qbsnd_queue_notes() > 32) qb_msleep(10);
    }
}

qb_i32 qb_play_fn(qb_i32 n) { (void)n; return qbsnd_queue_notes(); }
