/* M2b PS firmware entry point.
 *
 * One loop, three jobs, no interrupts of our own:
 *   1. drain the AXI frame record (acq_read) into a ring buffer;
 *   2. run the HTTP server (lwIP raw API, polled);
 *   3. keep lwIP's timers alive.
 *
 * The PL triggers the frames (acq_axi_regs o_sel_ext), so the loop never needs
 * to ask the host for anything.  At 11 ms per frame this loop has ~10 ms of
 * slack per frame; the read of one record is 7 AXI loads, i.e. a few
 * microseconds, so the ring only overflows if something else blocks for tens of
 * milliseconds.
 */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "xil_cache.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xparameters.h"

#include "lwip/tcp.h"

#include "acq.h"
#include "model.h"
#include "net.h"

/* lwIP 2.2 keeps these two in lwip/priv/tcp_priv.h, which is not a public
 * header; the echo template declares them the same way. */
void tcp_fasttmr(void);
void tcp_slowtmr(void);

static acq_frame g_ring[M2B_RING_CAP];
static int       g_head;
static int       g_count;
static m2b_conf  g_conf;

static int       g_have_layer;
static int       g_layer_idx;
#define M2B_LIFT_STEP_COUNTS 4096   /* counts per 2 mm layer (fpga/plan_cont.tcl) */
#define M2B_KEEP_EVERY       3      /* store 1 frame in N: 3x more layers fit */
static unsigned  g_keep_counter;
static int32_t   g_lift0;

static const char *g_state_ptr = "{}";
static double    g_state_built_at = -1.0;

/* ------------------------------------------------------------------ ingest */
static void ingest(acq_frame *f)
{
    /* Layers: the PS does not drive the lift, the host does, so pose_lift is the
     * only layer information available here.  Quantise the ABSOLUTE lift
     * position instead of counting changes: the old "d > 8 counts -> new layer"
     * rule incremented once every few frames of a 2 mm (4096 count) lift move,
     * producing hundreds of z keys, blowing past ALG_MAX_LAYERS and making
     * m2b_state_json() report an empty model after every multi-layer scan
     * (measured 2026-10-27: 1 layer/24 cells fine, 3 layers -> frames=0). */
    if (!g_have_layer) {
        g_lift0 = f->pose_lift;
        g_have_layer = 1;
    }
    {
        double k = ((double)g_lift0 - (double)f->pose_lift) / (double)M2B_LIFT_STEP_COUNTS;
        long   ki = (long)floor(k + 0.5);
        if (ki > 512)  { ki = 512; }
        if (ki < -512) { ki = -512; }
        /* Drop frames captured while the lift is travelling: they are off the
         * layer grid, blur the radius of the layer they land in, and eat ring
         * space that the layers need (about 900 frames per 2 mm move). */
        if (fabs(k - (double)ki) > 0.30) {
            return;
        }
        f->z_mm = g_conf.z0 + g_conf.dz * (double)ki;
    }

    /* Keep one frame in M2B_KEEP_EVERY: the per-cell median is estimated from
     * ~340 samples per layer and revolution, so a factor of 3 costs nothing
     * statistically while tripling how many layers fit in the 8192-frame ring
     * (8 -> ~20 layers; the JSON buffer becomes the next limit). */
    if ((g_keep_counter++ % M2B_KEEP_EVERY) != 0) {
        return;
    }

    f->arrive_s = acq_now_s();

    if (g_count >= M2B_RING_CAP) {
        g_head = (g_head + 1) % M2B_RING_CAP;
        g_count--;
    }
    g_ring[(g_head + g_count) % M2B_RING_CAP] = *f;
    g_count++;
}

/* ------------------------------------------------------------------- hooks */
static const char *state_cb(void)
{
    double now = acq_now_s();
    if (g_state_built_at < 0.0 || now - g_state_built_at > 0.4) {
        g_state_ptr = m2b_state_json(&g_conf, g_ring, M2B_RING_CAP, g_head, g_count, now);
        g_state_built_at = now;
    }
    return g_state_ptr;
}

/* ---------------------------------------------------------------- F1 pose ---
 * The pose is a second, independent AXI channel (1 kHz).  It gets its own tiny
 * route (/api/pose) because the page wants it at 20 Hz while /state is 60-120 KB:
 * folding the attitude into /state would make the picture lag by 700 ms.
 * "gx/gy/gz" are NOT the raw gyro; they are the PS-side rate of change of the
 * filtered angles, used only for display extrapolation between polls. */
static acq_pose      g_pose;
static m2b_pose_view g_pose_view;
static uint8_t       g_pose_seq;
static int           g_pose_have;
static double        g_pose_seen_s;
static int16_t       g_pose_prev[3];
static double        g_pose_rate[3];
static char          g_pose_json[256];

static void pose_poll(void)
{
    acq_pose p;
    double now;
    int i;

    if (!acq_read_pose(&p)) {
        return;                      /* no F1 block in this image, or a torn read */
    }
    now = acq_now_s();
    if (!g_pose_have || p.seq != g_pose_seq) {
        if (g_pose_have) {
            double dt = now - g_pose_seen_s;
            if (dt > 1e-4 && dt < 1.0) {
                int16_t cur[3];
                cur[0] = p.roll; cur[1] = p.pitch; cur[2] = p.yaw;
                for (i = 0; i < 3; i++) {
                    /* 16-bit difference: a +-180 wrap cancels instead of looking
                     * like a 360 deg jump */
                    int16_t d = (int16_t)(cur[i] - g_pose_prev[i]);
                    g_pose_rate[i] = acq_pose_deg(d) / dt;
                }
            }
        }
        g_pose_prev[0] = p.roll;
        g_pose_prev[1] = p.pitch;
        g_pose_prev[2] = p.yaw;
        g_pose_seen_s = now;
        g_pose_seq = p.seq;
        g_pose_have = 1;
    }
    g_pose = p;

    g_pose_view.ok = p.ok;
    g_pose_view.roll = acq_pose_deg(p.roll);
    g_pose_view.pitch = acq_pose_deg(p.pitch);
    g_pose_view.yaw = acq_pose_deg(p.yaw);
    g_pose_view.seq = (unsigned)p.seq;
    g_pose_view.age_ms = p.age_ms;
    g_pose_view.flags = (unsigned)p.flags;
    m2b_set_pose(&g_pose_view);
}

static const char *pose_cb(void)
{
    acq_pose p = g_pose;
    (void)snprintf(g_pose_json, sizeof g_pose_json,
                   "{\"ok\":%d,\"roll\":%.2f,\"pitch\":%.2f,\"yaw\":%.2f,"
                   "\"gx\":%.1f,\"gy\":%.1f,\"gz\":%.1f,"
                   "\"seq\":%u,\"tick_ms\":%.1f,\"age_ms\":%.1f,"
                   "\"flags\":%u,\"err\":%u,\"source\":\"PL\"}",
                   p.ok,
                   acq_pose_deg(p.roll), acq_pose_deg(p.pitch), acq_pose_deg(p.yaw),
                   g_pose_rate[0], g_pose_rate[1], g_pose_rate[2],
                   (unsigned)p.seq, p.tick_ms, p.age_ms,
                   (unsigned)p.flags, (unsigned)p.err_cnt);
    return g_pose_json;
}

static int command_cb(const char *path, const char *query)
{
    if (strcmp(path, "/api/ref") == 0) {
        /* /api/ref            snapshot the current model as the reference part
         * /api/ref?clear=1    drop the reference (back to no residual)
         * /api/ref?sigma=0.45&k=3   set the repeatability and the k factor */
        const char *p;
        if (strstr(query, "clear=1") != NULL) {
            m2b_ref_clear();
            return 1;
        }
        p = strstr(query, "sigma=");
        if (p != NULL) {
            m2b_ref_set_sigma(atof(p + 6));
        }
        p = strstr(query, "k=");
        if (p != NULL) {
            m2b_ref_set_k(atof(p + 2));
        }
        /* build the model now so g_alg is the current scan, then snapshot it */
        (void)m2b_state_json(&g_conf, g_ring, M2B_RING_CAP, g_head, g_count,
                             acq_now_s());
        return m2b_ref_capture_last() > 0;
    }
    if (strcmp(path, "/api/arm") == 0) {
        int on = -1;
        if (strncmp(query, "on=1", 4) == 0) {
            on = 1;
        } else if (strncmp(query, "on=0", 4) == 0) {
            on = 0;
        }
        if (on < 0) {
            return 0;
        }
        g_conf.armed = on;
        acq_arm(on);
        g_have_layer = 0;
        g_count = 0;
        g_head = 0;
        return 1;
    }
    if (strcmp(path, "/api/config") == 0) {
        int period = 0;
        int changed = m2b_apply_query(&g_conf, query, &period);
        if (period > 0) {
            int was = acq_armed();
            acq_arm(0);
            acq_init((uint16_t)period);
            if (was) {
                acq_arm(1);
            }
        }
        return changed;
    }
    return 0;
}

/* --------------------------------------------------------------------- main */
int main(void)
{
    net_hooks hooks;
    double last_fast, last_slow, last_print, last_hb;
#ifdef M2B_STATE_BENCH
    double last_bench;
#endif

    Xil_ICacheEnable();
    Xil_DCacheEnable();

    xil_printf("\r\n=== M2B_PS start ===\r\n");
    m2b_conf_default(&g_conf);
    acq_init(11);

    hooks.state_json = state_cb;
    hooks.pose_json = pose_cb;
    hooks.command = command_cb;
    net_init(&hooks, 0x02);

    /* Arm *after* the network is up.  net_init spends ~2 s in PHY setup, and
     * arming before it would count those frames as missed (measured 2026-10-27:
     * 200 missed at boot) even though nobody could have read them. */
    acq_arm(g_conf.armed);

    last_fast = last_slow = last_print = last_hb = acq_now_s();
#ifdef M2B_STATE_BENCH
    last_bench = last_hb;
#endif
    xil_printf("M2B_PS_ALIVE period=11ms armed=%d\r\n", g_conf.armed);

    for (;;) {
        acq_frame f;
        double now;

        while (acq_read(&f)) {
            ingest(&f);
        }
        pose_poll();
        net_poll();

        now = acq_now_s();
        if (now - last_fast > 0.25) {
            tcp_fasttmr();
            last_fast = now;
        }
        if (now - last_slow > 0.5) {
            tcp_slowtmr();
            last_slow = now;
        }
        /* Heartbeat into the unused AXI GPIO (0x4120_0000), because the CPU
         * writes DDR through its D-cache: a JTAG read of g_count sees stale
         * DDR, not what the loop believes.  The GPIO is strongly ordered, so
         *      ch1 = frames in the ring        ch2 = last STATUS
         * is the only way to watch the loop over JTAG when the network is not
         * wired.  (The handoff's M2b register table already marks this GPIO as
         * unused by the firmware.) */
        if (now - last_hb > 1.0) {
#ifndef M2B_NET_DEBUG
            Xil_Out32(0x41200000u, (uint32_t)g_count);
            Xil_Out32(0x41200008u, acq_status());
#endif
            last_hb = now;
        }
#ifdef M2B_STATE_BENCH
        /* Instrumentation build: build /state once per 5 s and publish the cost
         * (us) in GPIO ch1 so it can be read over JTAG without a network link.
         * This is the number that decides whether a 700 ms page poll can starve
         * the 90 fps frame loop. */
        if (now - last_bench > 5.0) {
            double b0 = acq_now_s();
            const char *js = m2b_state_json(&g_conf, g_ring, M2B_RING_CAP,
                                            g_head, g_count, b0);
            double b1 = acq_now_s();
            Xil_Out32(0x41200000u, (uint32_t)((b1 - b0) * 1.0e6));
            Xil_Out32(0x41200008u, (uint32_t)strlen(js));
            last_bench = b1;
        }
#endif
        if (now - last_print > 5.0) {
            uint32_t st = acq_status();
            xil_printf("M2B: frames=%d seq=%u missed=%u pending=%u\r\n",
                       g_count, (unsigned)(st >> 16), (unsigned)((st >> 8) & 0xFF),
                       (unsigned)(st & 1));
            last_print = now;
        }
    }
    return 0;
}
