#include "model.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "alg.h"

#define JSON_CAP   (192 * 1024)
#define TRACE_MAX  600
#define MESH_SEG   48

static char       g_json[JSON_CAP];
static alg_frame  g_frames[M2B_RING_CAP];
static alg_result g_alg;
static double     g_scratch[M2B_RING_CAP];
static m2b_pose_view g_pose;      /* F1 summary, see m2b_set_pose() */

void m2b_set_pose(const m2b_pose_view *p)
{
    if (p) {
        g_pose = *p;
    }
}

/* --------------------------------------------------------------- JSON writer */
typedef struct {
    char  *p;
    size_t left;
    int    overflow;
} jw;

static void jw_init(jw *w, char *buf, size_t cap)
{
    w->p = buf;
    w->left = cap;
    w->overflow = 0;
    if (cap) {
        buf[0] = '\0';
    }
}

static void jw_raw(jw *w, const char *s)
{
    size_t n = strlen(s);
    if (w->overflow || n + 1 > w->left) {
        w->overflow = 1;
        return;
    }
    memcpy(w->p, s, n);
    w->p += n;
    w->left -= n;
    *w->p = '\0';
}

static void jw_printf(jw *w, const char *fmt, ...)
{
    va_list ap;
    int n;
    if (w->overflow) {
        return;
    }
    va_start(ap, fmt);
    n = vsnprintf(w->p, w->left, fmt, ap);
    va_end(ap);
    if (n < 0 || (size_t)n >= w->left) {
        w->overflow = 1;
        return;
    }
    w->p += n;
    w->left -= (size_t)n;
}

/* finite doubles as numbers, everything else (incl. NaN) as null: the page does
 * .toFixed() on these and would throw on null only for r/t, which never are */
static void jw_num(jw *w, double v, int decimals)
{
    if (!isfinite(v)) {
        jw_raw(w, "null");
        return;
    }
    if (decimals == 0) {
        jw_printf(w, "%.0f", v);
    } else if (decimals == 1) {
        jw_printf(w, "%.1f", v);
    } else if (decimals == 2) {
        jw_printf(w, "%.2f", v);
    } else {
        jw_printf(w, "%.3f", v);
    }
}

static int cmp_double(const void *pa, const void *pb)
{
    double a = *(const double *)pa, b = *(const double *)pb;
    return (a < b) ? -1 : (a > b) ? 1 : 0;
}

static double median_copy(const double *v, int n)
{
    if (n <= 0) {
        return 0.0;
    }
    memcpy(g_scratch, v, (size_t)n * sizeof(double));
    qsort(g_scratch, (size_t)n, sizeof(double), cmp_double);
    if (n & 1) {
        return g_scratch[n / 2];
    }
    return 0.5 * (g_scratch[n / 2 - 1] + g_scratch[n / 2]);
}

/* ------------------------------------------------------------------- config */
void m2b_conf_default(m2b_conf *c)
{
    c->rot0 = 0.0;
    c->cpr = 4096.0;
    c->bin_deg = 15.0;
    c->continuity_us = 1.5;
    c->amp_min = 0.0;
    /* this rig's continuous plans start at z=+2 and step down 2 mm per layer
     * (live_run/plan_cont.tcl); the PS does not move the lift, so this is the
     * label the operator has to match to the plan. */
    c->z0 = 2.0;
    c->dz = -2.0;
    c->plan_layers = 3;
    c->min_peak = 4;
    c->armed = 1;
}

static double conf_get(const char *q, const char *key, double dflt, int *found)
{
    size_t klen = strlen(key);
    const char *p = q;
    while (p && *p) {
        if (strncmp(p, key, klen) == 0 && p[klen] == '=') {
            *found = 1;
            return atof(p + klen + 1);
        }
        p = strchr(p, '&');
        if (p) {
            p++;
        }
    }
    return dflt;
}

int m2b_apply_query(m2b_conf *c, const char *query, int *period_ms_out)
{
    int any = 0, f;
    double v;

    v = conf_get(query, "rot0", c->rot0, &f);
    if (f) { c->rot0 = v; any = 1; }
    v = conf_get(query, "z0", c->z0, &f);
    if (f) { c->z0 = v; any = 1; }
    v = conf_get(query, "dz", c->dz, &f);
    if (f) { c->dz = v; any = 1; }
    v = conf_get(query, "plan_layers", c->plan_layers, &f);
    if (f) { c->plan_layers = (int)v; any = 1; }
    v = conf_get(query, "period", 11.0, &f);
    if (f) {
        int p = (int)v;
        if (p < 11) {
            p = 11;   /* the PL's TX lockout is 10 ms; 11 ms is the measured floor */
        }
        *period_ms_out = p;
        any = 1;
    }
    return any;
}

/* -------------------------------------------------------------------- JSON */
static const alg_cell *find_cell(const alg_result *al, double z, int az)
{
    int i;
    for (i = 0; i < al->n_cells; i++) {
        if (al->cells[i].z_mm == z && al->cells[i].az_deg == az) {
            return &al->cells[i];
        }
    }
    return NULL;
}

/* ---- reference model + residual (PS-side anomaly detection) --------------- */
typedef struct {
    double z;
    int    az;
    double r;
} m2b_ref_cell;

static m2b_ref_cell  g_ref[ALG_MAX_CELLS];
static int           g_ref_n;
static double        g_sigma_mm = 0.45;    /* measured 2026-10-27, 3 rev/layer */
static int           g_sigma_measured;
static double        g_k_sigma  = 3.0;
static double        g_rmap[ALG_MAX_LAYERS][ALG_MAX_BINS];
static unsigned char g_rokm[ALG_MAX_LAYERS][ALG_MAX_BINS];
static double        g_drmap[ALG_MAX_LAYERS][ALG_MAX_BINS];
static double        g_drlist[ALG_MAX_CELLS];
static double        g_sortbuf[ALG_MAX_CELLS];

static int cmp_d(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x < y) ? -1 : ((x > y) ? 1 : 0);
}

void m2b_ref_clear(void) { g_ref_n = 0; }
int  m2b_ref_ready(void) { return g_ref_n > 0; }
int  m2b_ref_count(void) { return g_ref_n; }
void m2b_ref_set_sigma(double mm)
{
    if (mm > 0.0) { g_sigma_mm = mm; g_sigma_measured = 1; }
}
void m2b_ref_set_k(double k) { if (k > 0.0) g_k_sigma = k; }

int m2b_ref_capture_last(void)
{
    int i, n = 0;
    for (i = 0; i < g_alg.n_cells && n < ALG_MAX_CELLS; i++) {
        const alg_cell *c = &g_alg.cells[i];
        if (!c->valid) continue;
        g_ref[n].z = c->z_mm;
        g_ref[n].az = c->az_deg;
        g_ref[n].r = c->r_mm;
        n++;
    }
    g_ref_n = n;
    return n;
}

/* Appends the "residual" object (no leading comma, does not close the root). */
static void write_residual(jw *w, const double *zs, int nz, int nbin)
{
    int i, k, li, bi, co = 0, ndet = 0, ntest = 0;
    double thr, cm = 0.0, sd = 0.0, mx = 0.0;
    double bw;

    if (g_ref_n <= 0 || nz <= 0 || nbin <= 0) {
        jw_raw(w, "{\"available\":false,\"why\":\"PS: 还没有参考件——扫标准件后调用 "
                  "/api/ref\",\"noise_preview\":null}");
        return;
    }
    bw = 360.0 / (double)nbin;

    /* index the current model by (layer, bin) */
    memset(g_rokm, 0, sizeof(g_rokm));
    for (i = 0; i < g_alg.n_cells; i++) {
        const alg_cell *c = &g_alg.cells[i];
        if (!c->valid) continue;
        li = -1;
        for (k = 0; k < nz; k++) { if (zs[k] == c->z_mm) { li = k; break; } }
        if (li < 0) continue;
        bi = (int)((double)c->az_deg / bw + 0.5);
        if (bi < 0) { bi = 0; }
        if (bi >= nbin) { bi -= nbin; }
        g_rmap[li][bi] = c->r_mm;
        g_rokm[li][bi] = 1;
        ntest++;
    }
    for (li = 0; li < nz; li++) {
        for (bi = 0; bi < nbin; bi++) { g_drmap[li][bi] = NAN; }
    }
    for (i = 0; i < g_ref_n; i++) {
        li = -1;
        for (k = 0; k < nz; k++) { if (zs[k] == g_ref[i].z) { li = k; break; } }
        if (li < 0) continue;
        bi = (int)((double)g_ref[i].az / bw + 0.5);
        if (bi < 0) { bi = 0; }
        if (bi >= nbin) { bi -= nbin; }
        if (!g_rokm[li][bi]) continue;
        g_drmap[li][bi] = g_rmap[li][bi] - g_ref[i].r;
        g_drlist[co++] = g_drmap[li][bi];
    }
    if (co > 0) {
        memcpy(g_sortbuf, g_drlist, (size_t)co * sizeof(double));
        qsort(g_sortbuf, (size_t)co, sizeof(double), cmp_d);
        cm = (co & 1) ? g_sortbuf[co / 2]
                      : 0.5 * (g_sortbuf[co / 2 - 1] + g_sortbuf[co / 2]);
        for (i = 0; i < co; i++) {
            double d = g_drlist[i] - cm;
            sd += d * d;
        }
        sd = (co > 1) ? sqrt(sd / (double)(co - 1)) : 0.0;
    }
    thr = g_k_sigma * g_sigma_mm;
    if (thr < 1.5) { thr = 1.5; }
    for (li = 0; li < nz; li++) {
        for (bi = 0; bi < nbin; bi++) {
            double rc;
            if (isnan(g_drmap[li][bi])) continue;
            rc = g_drmap[li][bi] - cm;
            if (fabs(rc) > mx) { mx = fabs(rc); }
            if (fabs(rc) >= thr) { ndet++; }
        }
    }

    jw_raw(w, "{\"available\":true");
    jw_printf(w, ",\"sigma\":%.3f,\"sigma_source\":\"%s\",\"noise_cells\":%d",
              g_sigma_mm, g_sigma_measured ? "measured(3 rev/layer)" : "default",
              g_ref_n);
    jw_printf(w, ",\"thr\":%.3f,\"cm\":%.3f,\"res_sd\":%.3f,\"res_max_c\":%.3f",
              thr, cm, sd, mx);
    jw_printf(w, ",\"co_valid\":%d,\"acc_std\":%.3f,\"acc_test\":%.3f",
              co,
              (nz * nbin) ? (double)g_ref_n / (double)(nz * nbin) : 0.0,
              (nz * nbin) ? (double)ntest / (double)(nz * nbin) : 0.0);

    jw_raw(w, ",\"zs\":[");
    for (k = 0; k < nz; k++) { jw_printf(w, "%s%.3f", k ? "," : "", zs[k]); }
    jw_raw(w, "],\"azs\":[");
    for (k = 0; k < nbin; k++) { jw_printf(w, "%s%.0f", k ? "," : "", k * bw); }
    jw_raw(w, "],\"cmap\":[");
    for (li = 0; li < nz; li++) {
        jw_raw(w, li ? ",[" : "[");
        for (bi = 0; bi < nbin; bi++) {
            double v = g_drmap[li][bi];
            if (isnan(v)) {
                jw_raw(w, bi ? ",null" : "null");
            } else {
                jw_printf(w, "%s%.3f", bi ? "," : "", v);
            }
        }
        jw_raw(w, "]");
    }
    jw_raw(w, "],\"detections\":[");
    {
        int first = 1;
        for (li = 0; li < nz; li++) {
            for (bi = 0; bi < nbin; bi++) {
                double rc;
                if (isnan(g_drmap[li][bi])) continue;
                rc = g_drmap[li][bi] - cm;
                if (fabs(rc) < thr) continue;
                jw_printf(w,
                          "%s{\"az_deg\":%.0f,\"z_mm\":%.3f,\"residual_mm\":%.3f}",
                          first ? "" : ",", (double)bi * bw, zs[li],
                          g_drmap[li][bi]);
                first = 0;
            }
        }
    }
    jw_raw(w, "]");
    jw_printf(w, ",\"verdict\":\"%s\"}",
              ndet > 0 ? "DETECTED" : "NO_DETECTION");
}

const char *m2b_state_json(const m2b_conf *c, const acq_frame *ring, int ring_cap,
                           int head, int count, double now_s)
{
    jw w;
    alg_params par;
    int i, k, nz = 0;
    double layers[ALG_MAX_LAYERS];
    double azs[ALG_MAX_BINS];
    int nbin;
    int nframes = 0;
    double first_s = 0.0, last_s = 0.0;
    const alg_cell *cell;

    /* ---- copy the ring in age order and compute -------------------------- */
    /* Snap each frame's height to the planned layer grid (z0 + k*dz) and drop
     * frames taken while the lift was moving.  Without this a 3-layer scan
     * feeds the algorithm a continuum of heights (dozens of distinct z values
     * from the two 2 mm lift moves), which hits ALG_MAX_LAYERS and made
     * m2b_state_json() report an empty model after every multi-layer scan
     * (seen 2026-10-27: 24 cells fine, 72 cells -> frames=0). */
    for (i = 0; i < count && i < M2B_RING_CAP; i++) {
        const acq_frame *f = &ring[(head + i) % ring_cap];
        double z = f->z_mm;
        if (c->dz != 0.0) {
            double k  = (z - c->z0) / c->dz;
            double kr = floor(k + 0.5);
            if (fabs(k - kr) > 0.25) {
                continue;               /* mid-lift, not a planned layer */
            }
            z = c->z0 + kr * c->dz;
        }
        if (nframes < M2B_RING_CAP) {
            g_frames[nframes].z_mm = z;
            g_frames[nframes].pose_rot = f->pose_rot;
            g_frames[nframes].t_us = f->t_us;
            g_frames[nframes].amp = f->amp;
            g_frames[nframes].valid = f->valid;
            nframes++;
        }
    }

    alg_params_default(&par);
    par.rot0_counts = c->rot0;
    par.cpr = c->cpr;
    par.bin_deg = c->bin_deg;
    par.continuity_us = c->continuity_us;
    par.amp_min = c->amp_min;
    par.nbin = (int)llround(360.0 / c->bin_deg);
    nbin = par.nbin;

    if (nframes > 0) {
        first_s = ring[head].arrive_s;
        last_s = ring[(head + count - 1) % ring_cap].arrive_s;
        if (alg_compute(g_frames, nframes, &par, &g_alg) != 0) {
            nframes = 0;   /* capacity overflow: report an empty model, not lies */
        }
    }

    /* layers descending for the map, ascending for the profile */
    for (i = 0; i < g_alg.n_layers && nz < ALG_MAX_LAYERS; i++) {
        layers[nz++] = g_alg.zs[g_alg.n_layers - 1 - i];
    }
    for (i = 0; i < nbin && i < ALG_MAX_BINS; i++) {
        azs[i] = i * c->bin_deg;
    }

    jw_init(&w, g_json, sizeof(g_json));
    jw_raw(&w, "{\"now\":\"");
    {
        /* the PS has no wall clock; XTime seconds since boot is the honest time
         * base, and the page only uses it as a "last sync" label */
        unsigned long s = (unsigned long)now_s;
        jw_printf(&w, "%02lu:%02lu:%02lu", (s / 3600) % 100, (s / 60) % 60, s % 60);
    }
    jw_raw(&w, "\",\"elapsed_s\":");
    jw_num(&w, nframes ? (now_s - first_s) : 0.0, 1);
    jw_raw(&w, ",\"nominal_r\":14.0,\"geometry\":{\"a\":12.5,\"axis_y\":100.0,"
               "\"probe_y\":27.31,\"c_mm_us\":1.48}");
    jw_raw(&w, ",\"gt\":{\"az\":null,\"z\":0.0,\"radial\":null}");
    jw_printf(&w, ",\"min_peak\":%d,\"plan_layers\":%d", c->min_peak,
              c->plan_layers > 0 ? c->plan_layers : 3);
    /* F1: a *summary* of the attitude, for the record.  The page rotates from
     * /api/pose (20 Hz, ~180 B) so this 90 Hz page refresh does not need to
     * carry a 1 kHz stream. */
    jw_printf(&w, ",\"pose\":{\"ok\":%d,\"roll\":%.2f,\"pitch\":%.2f,\"yaw\":%.2f,"
                  "\"seq\":%u,\"age_ms\":%.1f,\"flags\":%u}",
              g_pose.ok, g_pose.roll, g_pose.pitch, g_pose.yaw,
              g_pose.seq, g_pose.age_ms, g_pose.flags);

    /* ---- the single run -------------------------------------------------- */
    jw_raw(&w, ",\"runs\":{\"std\":{");
    jw_raw(&w, "\"dir\":\"ps\",\"exists\":true,\"rot_mode\":\"config.rot0\",");
    jw_printf(&w, "\"meta\":{\"rot_start\":%.0f,\"counts_per_rev\":%.0f,\"bin_deg\":%.1f,"
                  "\"z0\":%.1f,\"dz\":%.1f,\"armed\":%d,\"frames\":%d},",
              c->rot0, c->cpr, c->bin_deg, c->z0, c->dz, c->armed, nframes);
    jw_printf(&w, "\"frames\":%d,", nframes);

    /* rate over the last 12 s of arrivals */
    {
        double rate = -1.0;
        int j0 = -1, j1 = -1;
        for (i = 0; i < nframes; i++) {
            double ts = ring[(head + i) % ring_cap].arrive_s;
            if (ts >= now_s - 12.0) {
                if (j0 < 0) {
                    j0 = i;
                }
                j1 = i;
            }
        }
        if (j0 >= 0 && j1 > j0) {
            double t0 = ring[(head + j0) % ring_cap].arrive_s;
            double t1 = ring[(head + j1) % ring_cap].arrive_s;
            if (t1 > t0) {
                rate = (double)(j1 - j0) / (t1 - t0);
            }
        }
        jw_raw(&w, "\"rate_fps\":");
        if (rate < 0.0) {
            jw_raw(&w, "null");
        } else {
            jw_num(&w, rate, 1);
        }
    }
    jw_raw(&w, ",\"silent_s\":");
    jw_num(&w, nframes ? (now_s - last_s) : 0.0, 1);
    jw_raw(&w, ",\"phase\":\"");
    if (nframes == 0) {
        jw_raw(&w, "启动/等待");
    } else if (now_s - last_s > 3.0) {
        jw_raw(&w, "升降/换层（不采帧）");
    } else {
        jw_raw(&w, "旋转采帧中");
    }
    jw_raw(&w, "\",\"last_new_s\":");
    jw_num(&w, nframes ? (now_s - last_s) : 0.0, 1);
    jw_raw(&w, ",\"elapsed_s\":");
    jw_num(&w, nframes ? (now_s - first_s) : 0.0, 1);
    jw_raw(&w, ",\"t_eff_us\":");
    if (nframes) {
        jw_num(&w, g_alg.t_eff_us, 3);
    } else {
        jw_raw(&w, "null");
    }

    /* layers / azs */
    jw_raw(&w, ",\"layers\":[");
    for (i = 0; i < nz; i++) {
        jw_printf(&w, "%s%.0f", i ? "," : "", layers[i]);
    }
    jw_raw(&w, "],\"azs\":[");
    for (i = 0; i < nbin; i++) {
        jw_printf(&w, "%s%.0f", i ? "," : "", azs[i]);
    }
    jw_raw(&w, "]");

    /* rmap / valid_map / tmap */
    jw_raw(&w, ",\"rmap\":[");
    for (k = 0; k < nz; k++) {
        jw_raw(&w, k ? ",[" : "[");
        for (i = 0; i < nbin; i++) {
            cell = find_cell(&g_alg, layers[k], (int)azs[i]);
            if (i) {
                jw_raw(&w, ",");
            }
            if (cell && isfinite(cell->r_mm)) {
                jw_num(&w, cell->r_mm, 3);
            } else {
                jw_raw(&w, "null");
            }
        }
        jw_raw(&w, "]");
    }
    jw_raw(&w, "],\"valid_map\":[");
    for (k = 0; k < nz; k++) {
        jw_raw(&w, k ? ",[" : "[");
        for (i = 0; i < nbin; i++) {
            cell = find_cell(&g_alg, layers[k], (int)azs[i]);
            jw_printf(&w, "%s%d", i ? "," : "", cell ? cell->valid : 0);
        }
        jw_raw(&w, "]");
    }
    jw_raw(&w, "],\"tmap\":[");
    for (k = 0; k < nz; k++) {
        jw_raw(&w, k ? ",[" : "[");
        for (i = 0; i < nbin; i++) {
            cell = find_cell(&g_alg, layers[k], (int)azs[i]);
            if (i) {
                jw_raw(&w, ",");
            }
            if (cell) {
                jw_num(&w, cell->t_us, 3);
            } else {
                jw_raw(&w, "null");
            }
        }
        jw_raw(&w, "]");
    }
    jw_raw(&w, "]");

    /* cell_rows, sorted by (-z, az) like live_model.py */
    jw_raw(&w, ",\"cell_rows\":[");
    {
        int first = 1;
        int li;
        for (li = 0; li < nz; li++) {
            for (i = 0; i < nbin; i++) {
                cell = find_cell(&g_alg, layers[li], (int)azs[i]);
                if (!cell) {
                    continue;
                }
                jw_printf(&w, "%s{\"z\":%.0f,\"az\":%.0f,\"n\":%d,\"used\":%d,\"peak\":%.0f,"
                              "\"t\":%.3f,\"t_circ\":%.3f,\"r\":%.3f,\"sd\":",
                          first ? "" : ",", cell->z_mm, (double)cell->az_deg, cell->n,
                          cell->used, cell->peak_med, cell->t_us, cell->t_circ_us,
                          cell->r_mm);
                first = 0;
                if (cell->has_sd) {
                    jw_num(&w, cell->sd_us, 3);
                } else {
                    jw_raw(&w, "null");
                }
                jw_printf(&w, ",\"ok\":%s}", cell->valid ? "true" : "false");
            }
        }
    }
    jw_raw(&w, "]");

    /* profile: one median radius per layer, ascending z (like build_lathe) */
    jw_raw(&w, ",\"profile\":[");
    {
        int first = 1;
        for (k = nz - 1; k >= 0; k--) {
            double rr[ALG_MAX_BINS];
            int nr = 0;
            for (i = 0; i < nbin; i++) {
                cell = find_cell(&g_alg, layers[k], (int)azs[i]);
                if (cell && cell->valid && isfinite(cell->r_mm)) {
                    rr[nr++] = cell->r_mm;
                }
            }
            if (!nr) {
                continue;
            }
            {
                double med = median_copy(rr, nr);
                double lo = rr[0], hi = rr[0];
                int q;
                for (q = 1; q < nr; q++) {
                    if (rr[q] < lo) lo = rr[q];
                    if (rr[q] > hi) hi = rr[q];
                }
                jw_printf(&w, "%s{\"z\":%.0f,\"r\":%.3f,\"spread\":%.3f,\"n\":%d,"
                              "\"circularity\":%.3f}",
                          first ? "" : ",", layers[k], med, hi - lo, nr, hi - lo);
                first = 0;
            }
        }
    }
    jw_raw(&w, "]");

    /* mesh: lathe of the profile, 48 segments, same winding as wscan.vertical */
    jw_raw(&w, ",\"mesh\":");
    {
        double pz[ALG_MAX_LAYERS], pr[ALG_MAX_LAYERS];
        int np = 0;
        for (k = nz - 1; k >= 0; k--) {
            double rr[ALG_MAX_BINS];
            int nr = 0;
            for (i = 0; i < nbin; i++) {
                cell = find_cell(&g_alg, layers[k], (int)azs[i]);
                if (cell && cell->valid && isfinite(cell->r_mm)) {
                    rr[nr++] = cell->r_mm;
                }
            }
            if (nr) {
                pz[np] = layers[k];
                pr[np] = median_copy(rr, nr);
                np++;
            }
        }
        if (np < 2) {
            jw_raw(&w, "null");
        } else {
            jw_raw(&w, "{\"vertices\":[");
            for (k = 0; k < np; k++) {
                for (i = 0; i < MESH_SEG; i++) {
                    double th = 2.0 * 3.14159265358979323846 * (double)i / MESH_SEG;
                    jw_printf(&w, "%s[%.2f,%.2f,%.2f]", (k || i) ? "," : "",
                              ALG_AXIS_X_MM + pr[k] * sin(th),
                              ALG_AXIS_Y_MM + pr[k] * cos(th), pz[k]);
                }
            }
            jw_raw(&w, "],\"faces\":[");
            {
                int first = 1, a, b;
                for (k = 0; k + 1 < np; k++) {
                    for (i = 0; i < MESH_SEG; i++) {
                        a = k * MESH_SEG + i;
                        b = k * MESH_SEG + (i + 1) % MESH_SEG;
                        jw_printf(&w, "%s[%d,%d,%d]", first ? "" : ",", a, b,
                                  a + MESH_SEG);
                        first = 0;
                        jw_printf(&w, ",[%d,%d,%d]", b, b + MESH_SEG, a + MESH_SEG);
                    }
                }
            }
            jw_raw(&w, "]");
            jw_printf(&w, ",\"stats\":{\"vertices\":%d,\"triangles\":%d,\"segments\":%d,"
                          "\"closed\":false,\"z_range_mm\":[%.0f,%.0f]}}",
                      np * MESH_SEG, 2 * MESH_SEG * (np - 1), MESH_SEG, pz[0], pz[np - 1]);
        }
    }

    /* trace: decimated per-frame points of the layer being scanned now */
    jw_raw(&w, ",\"trace\":[");
    if (nframes) {
        double cur_z = ring[(head + count - 1) % ring_cap].z_mm;
        int ncur = 0, step, first = 1;
        for (i = 0; i < nframes; i++) {
            if (ring[(head + i) % ring_cap].z_mm == cur_z) {
                ncur++;
            }
        }
        step = ncur / TRACE_MAX;
        if (step < 1) {
            step = 1;
        }
        {
            int seen = 0;
            for (i = 0; i < nframes; i++) {
                const acq_frame *f = &ring[(head + i) % ring_cap];
                double az;
                if (f->z_mm != cur_z) {
                    continue;
                }
                if (seen++ % step) {
                    continue;
                }
                az = ((double)f->pose_rot - c->rot0);
                az = fmod(az, c->cpr);
                if (az < 0.0) {
                    az += c->cpr;
                }
                az = az * 360.0 / c->cpr;
                jw_printf(&w, "%s{\"z\":%.0f,\"az\":%.2f,\"t\":%.3f,\"amp\":%.0f,"
                              "\"idx\":%u,\"cidx\":%u,\"cv\":%d}",
                          first ? "" : ",", cur_z, az, f->t_us, f->amp,
                          (unsigned)f->idx, (unsigned)f->cidx, f->cvalid);
                first = 0;
            }
        }
    }
    jw_raw(&w, "]");

    /* per_layer */
    jw_raw(&w, ",\"per_layer\":{");
    {
        int first = 1;
        for (k = 0; k < nz; k++) {
            int fn = 0, cn = 0, vn = 0, span_lo = 0, span_hi = 0, have = 0;
            for (i = 0; i < nframes; i++) {
                const acq_frame *f = &ring[(head + i) % ring_cap];
                if (f->z_mm != layers[k]) {
                    continue;
                }
                fn++;
                if (!have) {
                    span_lo = span_hi = f->pose_rot;
                    have = 1;
                } else {
                    if (f->pose_rot < span_lo) span_lo = f->pose_rot;
                    if (f->pose_rot > span_hi) span_hi = f->pose_rot;
                }
            }
            for (i = 0; i < g_alg.n_cells; i++) {
                if (g_alg.cells[i].z_mm != layers[k]) {
                    continue;
                }
                cn++;
                if (g_alg.cells[i].valid) {
                    vn++;
                }
            }
            jw_printf(&w, "%s\"%.0f\":{\"frames\":%d,\"cells\":%d,\"valid\":%d,"
                          "\"span_counts\":%d,\"span_deg\":%.1f,\"centroid_frames\":%d}",
                      first ? "" : ",", layers[k], fn, cn, vn, have ? span_hi - span_lo : 0,
                      have ? (span_hi - span_lo) * 360.0 / c->cpr : 0.0, fn);
            first = 0;
        }
    }
    jw_raw(&w, "}");

    jw_printf(&w, ",\"cells\":%d,\"valid_cells\":%d,\"quarantined\":%d",
              g_alg.n_cells, g_alg.n_valid_cells, g_alg.n_quarantined);
    jw_raw(&w, "}}");   /* close run, runs */

    jw_raw(&w, ",\"residual\":");
    write_residual(&w, layers, nz, nbin);
    jw_raw(&w, "}");    /* close the root object */

    if (w.overflow) {
        /* never hand the page truncated JSON: say so in a valid document */
        snprintf(g_json, JSON_CAP,
                 "{\"now\":\"--\",\"elapsed_s\":0,\"nominal_r\":14.0,"
                 "\"geometry\":{\"a\":12.5,\"axis_y\":100.0,\"probe_y\":27.31,"
                 "\"c_mm_us\":1.48},\"gt\":{\"az\":null,\"z\":0.0,\"radial\":null},"
                 "\"min_peak\":4,\"plan_layers\":3,"
                 "\"runs\":{\"std\":{\"frames\":%d,\"cells\":0,\"valid_cells\":0,"
                 "\"quarantined\":0,\"layers\":[],\"azs\":[],\"rmap\":[],"
                 "\"valid_map\":[],\"tmap\":[],\"cell_rows\":[],\"profile\":[],"
                 "\"mesh\":null,\"trace\":[],\"per_layer\":{},\"rate_fps\":null,"
                 "\"silent_s\":0,\"phase\":\"JSON 溢出\",\"t_eff_us\":null,"
                 "\"rot_mode\":\"config.rot0\",\"meta\":{}}},"
                 "\"residual\":{\"available\":false,\"why\":\"JSON buffer overflow\","
                 "\"noise_preview\":null}}",
                 nframes);
    }
    return g_json;
}
