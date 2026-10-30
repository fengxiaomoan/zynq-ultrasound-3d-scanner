#include "alg.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* M_PI is not in C99; M_PI on glibc/mingw is the same value. */
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* Scratch arrays, reused for every median.  A cell holds
 * frames/(layers*bins) frames in practice (~10..20); 4096 leaves room for a
 * stalled stage.  Static, not malloc: the bare-metal BSP heap is 8 KB and the
 * firmware must not depend on newlib's allocator.
 */
#define ALG_SCRATCH 8192
static double g_scratch[ALG_SCRATCH];
static double g_t_all[ALG_SCRATCH];
static double g_t_ok[ALG_SCRATCH];
static double g_amps[ALG_SCRATCH];
static double g_use[ALG_SCRATCH];
static double g_mad[ALG_SCRATCH];

static int cmp_double(const void *pa, const void *pb)
{
    double a = *(const double *)pa;
    double b = *(const double *)pb;
    return (a < b) ? -1 : (a > b) ? 1 : 0;
}

double alg_median(const double *v, int n)
{
    if (n <= 0) {
        return 0.0;
    }
    if (n > ALG_SCRATCH) {
        n = ALG_SCRATCH;
    }
    memcpy(g_scratch, v, (size_t)n * sizeof(double));
    qsort(g_scratch, (size_t)n, sizeof(double), cmp_double);
    if (n & 1) {
        return g_scratch[n / 2];
    }
    /* numpy.median: the mean of the two middle samples for an even count */
    return 0.5 * (g_scratch[n / 2 - 1] + g_scratch[n / 2]);
}

static double median_of(const double *v, int n) /* no clamping, caller checked */
{
    return alg_median(v, n);
}

static double wrap360(double x)
{
    double y = x - 360.0 * floor(x / 360.0);
    return (y < 0.0) ? y + 360.0 : y;
}

void alg_params_default(alg_params *par)
{
    par->cpr = (double)ALG_CPR_DEFAULT;
    par->bin_deg = ALG_BIN_DEG_DEFAULT;
    par->continuity_us = ALG_CONTINUITY_DEFAULT;
    par->amp_min = ALG_AMP_MIN_DEFAULT;
    par->rot0_counts = 0.0;
    par->nbin = (int)llround(360.0 / par->bin_deg);
}

/* one frame's azimuth/bin, exactly like continuous_scan.assign() */
static double frame_az_meas(const alg_frame *f, const alg_params *par)
{
    double d = (double)f->pose_rot - par->rot0_counts;
    double m = fmod(d, par->cpr);
    if (m < 0.0) {
        m += par->cpr;
    }
    return m * 360.0 / par->cpr;
}

static int frame_bin(double az_deg, const alg_params *par)
{
    /* Python: int(round(az / bin_deg)) % nbin  -- round() is half-to-even, which
     * is exactly what rint() does under the default FP rounding mode. */
    int b = (int)rint(az_deg / par->bin_deg);
    b %= par->nbin;
    if (b < 0) {
        b += par->nbin;
    }
    return b;
}

static int z_index(const alg_result *al, double z)
{
    int i;
    for (i = 0; i < al->n_layers; i++) {
        if (al->zs[i] == z) {
            return i;
        }
    }
    return -1;
}

int alg_compute(const alg_frame *frames, int n, const alg_params *par_in, alg_result *al)
{
    alg_params par = *par_in;
    double *t_all = NULL;
    double *t_ok = NULL;
    double *amps = NULL;
    double *use = NULL;
    double *mad = NULL;
    int i, c, li, bi;
    int per_cell[ALG_MAX_CELLS];
    double sum_sin[ALG_MAX_CELLS], sum_cos[ALG_MAX_CELLS];
    int slot[ALG_MAX_LAYERS][ALG_MAX_BINS];

    if (par.nbin <= 0) {
        alg_params_default(&par);
        par.rot0_counts = par_in->rot0_counts;
    }
    if (n <= 0) {
        return -1;
    }
    memset(al, 0, sizeof(*al));
    al->par = par;
    al->n_frames = n;

    /* ---- unique, ascending layer heights (dict keys in Python) ---------- */
    {
        double zs[ALG_MAX_LAYERS];
        int nz = 0;
        for (i = 0; i < n; i++) {
            double z = frames[i].z_mm;
            int seen = 0, k;
            for (k = 0; k < nz; k++) {
                if (zs[k] == z) {
                    seen = 1;
                    break;
                }
            }
            if (!seen) {
                if (nz >= ALG_MAX_LAYERS) {
                    return -1;
                }
                zs[nz++] = z;
            }
        }
        /* simple insertion sort: <= 32 layers */
        for (i = 1; i < nz; i++) {
            double v = zs[i];
            int k = i - 1;
            while (k >= 0 && zs[k] > v) {
                zs[k + 1] = zs[k];
                k--;
            }
            zs[k + 1] = v;
        }
        memcpy(al->zs, zs, (size_t)nz * sizeof(double));
        al->n_layers = nz;
    }

    for (li = 0; li < ALG_MAX_LAYERS; li++) {
        for (bi = 0; bi < ALG_MAX_BINS; bi++) {
            slot[li][bi] = -1;
        }
    }
    memset(per_cell, 0, sizeof(per_cell));
    memset(sum_sin, 0, sizeof(sum_sin));
    memset(sum_cos, 0, sizeof(sum_cos));

    /* ---- pass 1: assign frames to (z, bin) cells ------------------------ */
    for (i = 0; i < n; i++) {
        int zi = z_index(al, frames[i].z_mm);
        double azm = frame_az_meas(&frames[i], &par);
        int b;
        int ci;
        if (zi < 0) {
            return -1;
        }
        b = frame_bin(azm, &par);
        if (slot[zi][b] < 0) {
            if (al->n_cells >= ALG_MAX_CELLS) {
                return -1;
            }
            ci = al->n_cells++;
            slot[zi][b] = ci;
            memset(&al->cells[ci], 0, sizeof(alg_cell));
            al->cells[ci].z_mm = al->zs[zi];
            al->cells[ci].az_deg = (int)((b * (int)par.bin_deg) % 360);
            al->cells[ci].az_meas_deg = 0.0;
        } else {
            ci = slot[zi][b];
        }
        per_cell[ci]++;
        /* circular mean of the measured azimuths, like circ_mean_deg() */
        {
            double r = azm * (M_PI / 180.0);
            sum_sin[ci] += sin(r);
            sum_cos[ci] += cos(r);
        }
    }

    /* ---- pass 2: per-cell robust estimate -------------------------------- */
    if (n > ALG_SCRATCH) {
        return -1;
    }
    t_all = g_t_all;
    t_ok = g_t_ok;
    amps = g_amps;
    use = g_use;
    mad = g_mad;

    for (c = 0; c < al->n_cells; c++) {
        alg_cell *cell = &al->cells[c];
        int na = 0, nok = 0, k;
        double med, m;
        for (i = 0; i < n; i++) {
            int zi = z_index(al, frames[i].z_mm);
            double azm;
            int b;
            if (zi < 0) {
                continue;
            }
            azm = frame_az_meas(&frames[i], &par);
            b = frame_bin(azm, &par);
            if (slot[zi][b] != c) {
                continue;
            }
            t_all[na] = frames[i].t_us;
            amps[na] = frames[i].amp;
            na++;
            if (frames[i].valid && frames[i].amp >= par.amp_min) {
                t_ok[nok++] = frames[i].t_us;
            }
        }
        if (na == 0) {
            continue;
        }
        cell->n = na;
        cell->used = nok;
        cell->fallback = (nok == 0) ? 1 : 0;
        for (k = 0; k < (cell->fallback ? na : nok); k++) {
            use[k] = cell->fallback ? t_all[k] : t_ok[k];
        }
        cell->t_us = median_of(use, cell->fallback ? na : nok);
        cell->lead_us = cell->t_us;
        cell->peak_med = median_of(amps, na);
        if ((cell->fallback ? na : nok) >= 2) {
            med = cell->t_us;
            for (k = 0; k < (cell->fallback ? na : nok); k++) {
                mad[k] = fabs(use[k] - med);
            }
            m = median_of(mad, cell->fallback ? na : nok);
            cell->sd_us = 1.4826 * m;
            cell->has_sd = 1;
        }
        {
            double ang = atan2(sum_sin[c] / (double)na, sum_cos[c] / (double)na);
            cell->az_meas_deg = wrap360(ang * (180.0 / M_PI));
        }
    }

    /* ---- pass 3: circular 3-cell continuity gate, per layer --------------- */
    for (li = 0; li < al->n_layers; li++) {
        int idx[ALG_MAX_BINS];
        int m = 0, a;
        for (bi = 0; bi < par.nbin; bi++) {
            int ci = slot[li][bi];
            if (ci >= 0) {
                idx[m++] = ci;
            }
        }
        for (a = 0; a < m; a++) {
            double nb[3];
            int left = (a - 1 + m) % m;
            int right = (a + 1) % m;
            nb[0] = al->cells[idx[left]].t_us;
            nb[1] = al->cells[idx[a]].t_us;
            nb[2] = al->cells[idx[right]].t_us;
            al->cells[idx[a]].t_circ_us = median_of(nb, 3);
            al->cells[idx[a]].outlier =
                fabs(al->cells[idx[a]].t_us - al->cells[idx[a]].t_circ_us) > par.continuity_us;
        }
    }

    /* ---- pass 4: nominal-14 mm anchor and radius ------------------------- */
    {
        double good[ALG_MAX_CELLS];
        int ng = 0;
        double med_t, path14, t_eff;
        for (c = 0; c < al->n_cells; c++) {
            if (!al->cells[c].fallback && !al->cells[c].outlier) {
                good[ng++] = al->cells[c].t_us;
            }
        }
        if (ng == 0) {
            double all[ALG_MAX_CELLS];
            for (c = 0; c < al->n_cells; c++) {
                all[c] = al->cells[c].t_us;
            }
            med_t = median_of(all, al->n_cells);
        } else {
            med_t = median_of(good, ng);
        }
        path14 = 2.0 * sqrt(ALG_A_MM * ALG_A_MM +
                            (ALG_AXIS_Y_MM - ALG_PROBE_Y_MM - ALG_NOMINAL_R) *
                            (ALG_AXIS_Y_MM - ALG_PROBE_Y_MM - ALG_NOMINAL_R));
        t_eff = med_t - path14 / ALG_C_MM_US;
        al->t_eff_us = t_eff;
        for (c = 0; c < al->n_cells; c++) {
            double path = (al->cells[c].t_us - t_eff) * ALG_C_MM_US;
            double half = path / 2.0;
            double inner = half * half - ALG_A_MM * ALG_A_MM;
            al->cells[c].r_mm = (inner > 0.0)
                ? (ALG_AXIS_Y_MM - ALG_PROBE_Y_MM - sqrt(inner))
                : (double)NAN;
            al->cells[c].valid = (!al->cells[c].fallback && !al->cells[c].outlier) ? 1 : 0;
            if (al->cells[c].valid) {
                al->n_valid_cells++;
            } else {
                al->n_quarantined++;
            }
        }
    }

    /* the scratch arrays are static; nothing to free */

    /* ---- sort by (z, az) like sorted(cells.items()) ---------------------- */
    for (i = 1; i < al->n_cells; i++) {
        alg_cell v = al->cells[i];
        int k = i - 1;
        while (k >= 0 && (al->cells[k].z_mm > v.z_mm ||
                          (al->cells[k].z_mm == v.z_mm && al->cells[k].az_deg > v.az_deg))) {
            al->cells[k + 1] = al->cells[k];
            k--;
        }
        al->cells[k + 1] = v;
    }
    return 0;
}

int alg_write_points_csv(const alg_result *al, void *fh_ptr)
{
    FILE *fh = (FILE *)fh_ptr;
    int c;
    if (!fh) {
        return -1;
    }
    fprintf(fh, "z_mm,az_deg,frames,frames_used,fallback,peak_med,peak_max,"
                "t_centroid_us,t_lead_us,t_circ_median_us,outlier,r_mm,valid,"
                "az_meas_deg,per_frame_sd_us\n");
    for (c = 0; c < al->n_cells; c++) {
        const alg_cell *p = &al->cells[c];
        /* NOTE: the peak_max column carries peak_med -- continuous_scan.py does
         * the same (its writer passes p["peak_med"] twice), and the gate is
         * "same file", quirks included. */
        fprintf(fh, "%+.0f,%.0f,%d,%d,%d,%.1f,%.1f,%.3f,%.3f,%.3f,%d,%.3f,%d,%.2f,",
                p->z_mm, (double)p->az_deg, p->n, p->used, p->fallback,
                p->peak_med, p->peak_med, p->t_us, p->lead_us, p->t_circ_us,
                p->outlier, p->r_mm, p->valid, p->az_meas_deg);
        if (p->has_sd) {
            fprintf(fh, "%.3f\n", p->sd_us);
        } else {
            fprintf(fh, "\n");
        }
    }
    return 0;
}
