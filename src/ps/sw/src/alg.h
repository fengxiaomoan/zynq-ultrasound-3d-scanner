/* Portable C port of tools/continuous_scan.py's binning + geometry.
 *
 * Why a separate, dependency-free file: the acceptance gate for M2b is "the C
 * algorithm and tools/continuous_scan.py produce the same points.csv from the
 * same frames".  The only way to prove that without a board is to compile this
 * exact file twice -- once with the host gcc (host/host_main.c) and once with
 * arm-none-eabi-gcc for the PS -- and to diff its output against Python's.
 *
 * So: no Xilinx headers, no lwIP, no floating point quirks of our own.  Every
 * arithmetic step below mirrors the Python line it names, including
 *   * Python's round() (half-to-even) for the azimuth bin,
 *   * numpy's median (mean of the two middle samples when the count is even),
 *   * the 3-cell circular median gate,
 *   * the nominal-14 mm t_eff anchor and r = 72.69 - sqrt((path/2)^2 - 12.5^2),
 *   * the points.csv formatting (including the historic quirk that the
 *     peak_max column is written from peak_med).
 */
#ifndef ACOUSTIC_ALG_H
#define ACOUSTIC_ALG_H

#include <stddef.h>

/* geometry, identical to tools/robust_scan.py */
#define ALG_A_MM        12.5
#define ALG_AXIS_Y_MM   100.0
#define ALG_PROBE_Y_MM  27.31
#define ALG_C_MM_US     1.48
#define ALG_AXIS_X_MM   75.0
#define ALG_NOMINAL_R   14.0

#define ALG_CPR_DEFAULT       4096
#define ALG_BIN_DEG_DEFAULT   15.0
#define ALG_CONTINUITY_DEFAULT 1.5
#define ALG_AMP_MIN_DEFAULT   0.0

#define ALG_MAX_LAYERS 32
#define ALG_MAX_BINS   64
#define ALG_MAX_CELLS  (ALG_MAX_LAYERS * ALG_MAX_BINS)

typedef struct {
    double z_mm;      /* height of the layer this frame belongs to */
    int    pose_rot;  /* commanded rotation counter, latched on capture_start */
    double t_us;      /* centroid time: cent_idx * 0.2 us */
    double amp;       /* the 40-bit word's amplitude (peak_med uses it) */
    int    valid;      /* used as a *valid flag* only (1 = usable) */
} alg_frame;

typedef struct {
    double z_mm;
    int    az_deg;      /* bin centre, snapped to the fixed grid */
    int    n;           /* frames in the cell */
    int    used;        /* frames passing (valid && amp >= amp_min) */
    int    fallback;    /* 1 = no frame passed, cell used all frames */
    double peak_med;
    double t_us;
    double lead_us;
    double sd_us;       /* 1.4826 * MAD of the used times; 0 when not defined */
    int    has_sd;
    double t_circ_us;
    int    outlier;
    double r_mm;        /* NaN when the path is shorter than 2*A */
    int    valid;       /* not fallback and not outlier: what the model uses */
    double az_meas_deg; /* circular mean of the frames' measured azimuths */
} alg_cell;

typedef struct {
    double cpr;
    double bin_deg;
    double continuity_us;
    double amp_min;
    double rot0_counts;  /* pose_rot count at azimuth 0 (continuous runs) */
    int    nbin;
} alg_params;

typedef struct {
    alg_params par;
    alg_cell   cells[ALG_MAX_CELLS];
    int        n_cells;
    double     zs[ALG_MAX_LAYERS];   /* ascending, unique layer heights */
    int        n_layers;
    double     t_eff_us;
    int        n_frames;
    int        n_valid_cells;
    int        n_quarantined;
} alg_result;

/* Fill *par with the defaults above. */
void alg_params_default(alg_params *par);

/* Compute the binned model.  Returns 0 on success, -1 when the frame count is
 * zero or a capacity is exceeded.  al->cells is sorted by (z, az) exactly like
 * the CSV writer in continuous_scan.py. */
int alg_compute(const alg_frame *frames, int n, const alg_params *par, alg_result *al);

/* Write the points.csv body (header included) to fh.  Returns 0 on success. */
int alg_write_points_csv(const alg_result *al, void *fh);

/* median helpers are exposed because the host harness's self-test uses them */
double alg_median(const double *v, int n);

#endif /* ACOUSTIC_ALG_H */
