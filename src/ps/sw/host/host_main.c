/* Host-side acceptance harness for the M2b algorithm port.
 *
 * Reads frames.csv (written by tools/m2b_frames.py from a real
 * manifest.jsonl), runs the *same* alg.c that the PS firmware runs, and writes
 * a points.csv in the exact schema of tools/continuous_scan.py.
 *
 *   gcc -O2 -std=c99 -I../../src host_main.c ../../src/alg.c -lm -o m2b_alg
 *   ./m2b_alg frames.csv points_c.csv
 *
 * Then tools/m2b_gate.py compares points_c.csv with the Python run's points.csv.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "alg.h"

int main(int argc, char **argv)
{
    FILE *in;
    FILE *out;
    char line[512];
    alg_frame *frames = NULL;
    int cap = 0, n = 0;
    alg_params par;
    alg_result *al;
    int rc;

    if (argc < 3) {
        fprintf(stderr, "usage: %s frames.csv points.csv [rot0] [cpr] [bin_deg] [continuity] [amp_min]\n",
                argv[0]);
        return 2;
    }
    alg_params_default(&par);
    if (argc > 3) par.rot0_counts = atof(argv[3]);
    if (argc > 4) par.cpr = atof(argv[4]);
    if (argc > 5) par.bin_deg = atof(argv[5]);
    if (argc > 6) par.continuity_us = atof(argv[6]);
    if (argc > 7) par.amp_min = atof(argv[7]);
    par.nbin = (int)(360.0 / par.bin_deg + 0.5);

    in = fopen(argv[1], "r");
    if (!in) {
        perror(argv[1]);
        return 1;
    }
    if (!fgets(line, sizeof(line), in)) {   /* header */
        fprintf(stderr, "empty %s\n", argv[1]);
        fclose(in);
        return 1;
    }
    while (fgets(line, sizeof(line), in)) {
        char *p = line;
        char *end;
        alg_frame f;
        if (line[0] == '\n' || line[0] == '\r' || line[0] == '#') {
            continue;
        }
        f.z_mm = strtod(p, &end); p = end;
        if (*p == ',') p++;
        f.pose_rot = (int)strtol(p, &end, 10); p = end;
        if (*p == ',') p++;
        f.t_us = strtod(p, &end); p = end;
        if (*p == ',') p++;
        f.amp = strtod(p, &end); p = end;
        if (*p == ',') p++;
        f.valid = (int)strtol(p, &end, 10);
        if (n == cap) {
            cap = cap ? cap * 2 : 1024;
            frames = (alg_frame *)realloc(frames, (size_t)cap * sizeof(alg_frame));
            if (!frames) {
                return 1;
            }
        }
        frames[n++] = f;
    }
    fclose(in);

    al = (alg_result *)calloc(1, sizeof(alg_result));
    if (!al) {
        return 1;
    }
    rc = alg_compute(frames, n, &par, al);
    if (rc != 0) {
        fprintf(stderr, "alg_compute failed (frames=%d, rc=%d)\n", n, rc);
        return 1;
    }
    out = fopen(argv[2], "w");
    if (!out) {
        perror(argv[2]);
        return 1;
    }
    alg_write_points_csv(al, out);
    fclose(out);
    printf("frames=%d cells=%d layers=%d valid=%d t_eff=%.3f\n",
           n, al->n_cells, al->n_layers, al->n_valid_cells, al->t_eff_us);
    free(frames);
    free(al);
    return 0;
}
