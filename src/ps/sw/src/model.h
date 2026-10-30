/* On-board model + /state JSON for the M2b web page.
 *
 * The JSON is structurally the same object tools/live_model.py serves, so
 * tools/live_model_page.html works unchanged:
 *
 *   {now, elapsed_s, nominal_r, geometry, gt, min_peak, plan_layers,
 *    runs: {"std": {frames, rate_fps, phase, t_eff_us, layers, azs, rmap,
 *                   valid_map, tmap, cell_rows, profile, mesh, trace,
 *                   per_layer, cells, valid_cells, quarantined, ...}},
 *    residual: {available:false, why:...}}
 *
 * What the PS can and cannot say is stated in the JSON itself:
 *   * there is only ONE run on the board, so it is published as "std" and the
 *     residual block is explicitly unavailable (the defect comparison needs two
 *     runs and lives on the PC);
 *   * z comes from the layer order (z0 + k*dz), because the PS does not drive
 *     the lift -- the host still commands it over VIO and only its step counter
 *     is visible in the frame record;
 *   * pose_rot is a commanded step counter, not an encoder.
 */
#ifndef M2B_MODEL_H
#define M2B_MODEL_H

#include <stddef.h>

#include "acq.h"

#define M2B_RING_CAP 8192

typedef struct {
    double rot0;          /* pose_rot count at azimuth 0 */
    double cpr;           /* counts per revolution */
    double bin_deg;
    double continuity_us;
    double amp_min;
    double z0;            /* z of the first layer seen */
    double dz;            /* z step per detected layer change (signed) */
    int    plan_layers;   /* only for the page's progress bar */
    int    min_peak;
    int    armed;
} m2b_conf;

void m2b_conf_default(m2b_conf *c);

/* ---- F1 pose summary carried inside /state -------------------------------
 * It is a summary for the record/replay, NOT the page's rotation source: the
 * page polls /api/pose instead (see net.h).  Unset => {"ok":0,...}. */
typedef struct {
    int      ok;
    double   roll, pitch, yaw;   /* degrees */
    unsigned seq;
    double   age_ms;
    unsigned flags;
} m2b_pose_view;

void m2b_set_pose(const m2b_pose_view *p);

/* Build (and cache) the JSON for the current ring contents.  Returns a pointer
 * to a static buffer; never NULL.  now_s is XTime seconds. */
const char *m2b_state_json(const m2b_conf *c, const acq_frame *ring, int ring_cap,
                           int head, int count, double now_s);

/* Handle /api/config?z0=..&dz=..&rot0=..&period=..&plan_layers=..
 * Returns 1 when at least one key was applied (the caller then pushes period to
 * the PL), 0 for an unknown query. */
int m2b_apply_query(m2b_conf *c, const char *query, int *period_ms_out);

/* ---- PS-side anomaly detection -------------------------------------------
 * /api/ref snapshots the current model as the reference part; every later
 * /state then carries a `residual` block: per-cell r - r_ref, a threshold taken
 * from the measured repeatability, and the cells that exceed it. */
int  m2b_ref_capture_last(void);   /* snapshot the last built model */
int  m2b_ref_ready(void);
int  m2b_ref_count(void);
void m2b_ref_clear(void);
void m2b_ref_set_sigma(double mm); /* repeatability of one scan (default 0.45) */
void m2b_ref_set_k(double k);      /* threshold = max(k*sigma, 1.5) mm */

#endif /* M2B_MODEL_H */
