#include "acq.h"

#include "xil_io.h"
#include "xparameters.h"

/* The SDT BSP exposes xiltimer, not XTime_GetTime, and we do not need an
 * interrupt: the Cortex-A9 global timer is a free-running 64-bit counter at
 * CPU/2, which is all "when did this frame arrive" needs.  Read lo/hi/lo and
 * retry on a low-word wrap so the pair is always coherent. */
#define GT_BASE 0xF8F00200u
#define GT_HZ   ((double)XPAR_CPU_CORE_CLOCK_FREQ_HZ / 2.0)

static uint32_t g_last_seq;
static int      g_have_last;
static uint32_t g_missed;
static int      g_armed;

/* F1 pose bookkeeping (M3) */
static uint32_t g_f1_n;
static uint8_t  g_f1_seq_last;
static uint8_t  g_f1_have_seq;
static double   g_f1_seen_s;

static inline uint32_t rd(uint32_t off) { return Xil_In32(ACQ_BASE + off); }
static inline void     wr(uint32_t off, uint32_t v) { Xil_Out32(ACQ_BASE + off, v); }

double acq_now_s(void)
{
    uint32_t lo, hi, hi2;
    /* Read hi/lo/hi.  The low word free-runs at CPU/2, so it changes between any
     * two reads -- the obvious "compare lo with lo2" loop never terminates (it
     * froze the first on-board run at 0x10046c).  Only the HIGH word can tell us
     * whether the pair we got is coherent. */
    do {
        hi = Xil_In32(GT_BASE + 4u);
        lo = Xil_In32(GT_BASE);
        hi2 = Xil_In32(GT_BASE + 4u);
    } while (hi != hi2);
    return (double)(((uint64_t)hi << 32) | (uint64_t)lo) / GT_HZ;
}

void acq_init(uint16_t period_ms)
{
    g_last_seq = 0;
    g_have_last = 0;
    g_missed = 0;
    g_armed = 0;
    g_f1_n = 0;
    g_f1_seq_last = 0;
    g_f1_have_seq = 0;
    g_f1_seen_s = 0.0;
    /* the datapath refuses frames faster than its own 10 ms TX lockout; the
     * handoff measured 90.7 fps at 11 ms, so 11 ms is the configured default.
     * This is a floor the caller can only raise: acq_init clamps it. */
    if (period_ms < 11) {
        period_ms = 11;
    }
    wr(ACQ_PERIOD_MS, period_ms);
    wr(ACQ_CTRL, 0);          /* disarmed, VIO trigger source */
    wr(ACQ_ACK, 1);           /* clear a stale pending record */
}

void acq_arm(int on)
{
    uint16_t period = (uint16_t)rd(ACQ_PERIOD_MS);
    if (period < 11) {
        period = 11;
    }
    if (on) {
        /* contract of acq_axi_regs: write the period first, then arm; the
         * multi-bit period is latched on the rising edge of the synchronised
         * arm bit, so writing it afterwards would be ignored. */
        wr(ACQ_PERIOD_MS, period);
        wr(ACQ_CTRL, 0x00010001u);   /* sel_ext | arm */
        g_missed = 0;
        g_have_last = 0;
    } else {
        wr(ACQ_CTRL, 0x00010000u);   /* sel_ext stays, arm clears */
    }
    g_armed = on ? 1 : 0;
}

int acq_armed(void) { return g_armed; }
uint32_t acq_status(void) { return rd(ACQ_STATUS); }

uint32_t acq_missed(void)
{
    uint32_t st = rd(ACQ_STATUS);
    g_missed = (st >> 8) & 0xFFu;
    return g_missed;
}

int acq_read(acq_frame *f)
{
    uint32_t st = rd(ACQ_STATUS);
    uint32_t s1, s2, plo, phi, clo, chi, prot, plft;

    if ((st & 1u) == 0u) {
        return 0;
    }
    s1 = rd(ACQ_SEQ) & 0xFFFFu;
    plo = rd(ACQ_PEAK_LO);
    phi = rd(ACQ_PEAK_HI) & 0xFFu;
    clo = rd(ACQ_CENT_LO);
    chi = rd(ACQ_CENT_HI) & 0xFFFFFFu;
    prot = rd(ACQ_POSE_ROT);
    plft = rd(ACQ_POSE_LIFT);
    s2 = rd(ACQ_SEQ) & 0xFFFFu;

    if (s1 != s2) {
        /* a frame landed mid-read: the payload may be a mix, so do not ACK and
         * retry on the next poll (the pending bit is still set) */
        return 0;
    }
    if (g_have_last && s1 == g_last_seq) {
        wr(ACQ_ACK, 1);      /* already consumed: drop the duplicate */
        return 0;
    }

    f->seq = s1;
    f->peak_word = ((uint64_t)phi << 32) | (uint64_t)plo;
    f->cent_word = ((uint64_t)chi << 32) | (uint64_t)clo;
    f->pose_rot = (int32_t)prot;
    f->pose_lift = (int32_t)plft;

    /* peak_word = {valid, frame[12:0], idx[9:0], amp[15:0]} (40 bit) */
    f->valid = (int)((f->peak_word >> 39) & 1u);
    f->idx = (uint32_t)((f->peak_word >> 16) & 0x3FFu);
    f->amp = (double)(f->peak_word & 0xFFFFu);

    /* cent_word = {valid, idx[9:0], sum_w[17:0], sum_kw[26:0]} (56 bit) */
    f->cvalid = (int)((f->cent_word >> 55) & 1u);
    f->cidx = (uint32_t)((f->cent_word >> 45) & 0x3FFu);
    if (f->cvalid) {
        f->t_us = (double)f->cidx * 0.2;
        f->valid = 1;
    } else {
        f->t_us = (double)f->idx * 0.2;
    }

    f->gap = 0;
    if (g_have_last && (uint32_t)((s1 - g_last_seq) & 0xFFFFu) != 1u) {
        f->gap = 1;          /* seq jumped: at least one record was overwritten */
    }
    g_last_seq = s1;
    g_have_last = 1;
    wr(ACQ_ACK, 1);
    return 1;
}

/* ------------------------------------------------------------------ F1 pose */
double acq_pose_deg(int16_t counts)
{
    return (double)counts / ACQ_F1_CPD;
}

int acq_read_pose(acq_pose *p)
{
    uint32_t h1, lo, mid, tk, h2;

    if (!p) {
        return 0;
    }
    h1 = rd(ACQ_F1_HDR);
    lo = rd(ACQ_F1_POSE_LO);
    mid = rd(ACQ_F1_POSE_MID);
    tk = rd(ACQ_F1_TICK);
    h2 = rd(ACQ_F1_HDR);

    if (h1 != h2) {
        /* a 1 kHz sample landed in the middle of the sequence: the four words may
         * belong to two different attitudes, so drop this one and retry */
        return 0;
    }
    if (((h1 >> 16) & 0xFFFFu) != ACQ_F1_MAGIC) {
        /* no F1 block in this image (M2b): say "no attitude", never fake one */
        p->ok = 0;
        p->seq = 0;
        p->flags = 0;
        p->age_ms = 0.0;
        p->n = g_f1_n;
        return 0;
    }

    p->seq   = (uint8_t)((h1 >> 8) & 0xFFu);
    p->flags = (uint8_t)(h1 & 0xFFu);
    p->ok      = (p->flags & 0x01u) ? 1 : 0;
    p->init    = (p->flags & 0x02u) ? 1 : 0;
    p->i2c_err = (p->flags & 0x04u) ? 1 : 0;
    p->stuck   = (p->flags & 0x08u) ? 1 : 0;

    /* Word layout (merged_top_bd_f1.v, the single source of truth):
     *   0x30 = word[31:0]  = {yaw[31:16], 8'h00, err_cnt[7:0]}
     *   0x34 = word[63:32] = {roll[31:16], pitch[15:0]}
     * 2026-10-27: the first version decoded these as {yaw,err} low-first and
     * {roll,pitch} low-first, which the doc's register table also said -- but the
     * RTL packs the HIGH half first (it is a slice of the 128-bit pose word).  On
     * the board that showed up as yaw=0 and err=57290 (= -45.3 deg of yaw read as
     * an error count). */
    p->yaw     = (int16_t)((lo >> 16) & 0xFFFFu);
    p->err_cnt = (uint16_t)(lo & 0xFFu);
    p->roll    = (int16_t)((mid >> 16) & 0xFFFFu);
    p->pitch   = (int16_t)(mid & 0xFFFFu);

    p->tick = tk;
    /* 32-bit 50 MHz tick wraps every 85.9 s: tick_ms is "ms since PL reset",
     * modulo that, and is meant for logging / E3 analysis, not for age */
    p->tick_ms = (double)tk * 1000.0 / ACQ_F1_TICK_HZ;

    if (!g_f1_have_seq || p->seq != g_f1_seq_last) {
        g_f1_seq_last = p->seq;
        g_f1_have_seq = 1;
        g_f1_seen_s = acq_now_s();
        g_f1_n++;
    }
    p->n = g_f1_n;
    p->age_ms = (acq_now_s() - g_f1_seen_s) * 1000.0;
    if (p->age_ms < 0.0) {
        p->age_ms = 0.0;
    }
    return 1;
}
