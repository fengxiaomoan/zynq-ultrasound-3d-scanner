/* Host harness for model.c: feed a real frames.csv through the *same* JSON
 * builder the PS runs and write the /state document.
 *
 * This is how /state is verified without a board: the page's contract is the
 * JSON, and the JSON can be produced from recorded frames on the PC.  See
 * tools/m2b_state_gate.py, which parses the result and cross-checks it against
 * the points.csv of the same run.
 *
 *   gcc -O2 -std=c99 -I../../src state_main.c ../../src/model.c ../../src/alg.c -lm -o m2b_state
 *   ./m2b_state frames.csv state.json [z0] [dz] [rot0]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acq.h"
#include "alg.h"
#include "model.h"

static acq_frame g_ring[M2B_RING_CAP];

int main(int argc, char **argv)
{
    FILE *in;
    FILE *out;
    char line[512];
    int n = 0;
    m2b_conf conf;
    const char *js;

    if (argc < 3) {
        fprintf(stderr, "usage: %s frames.csv state.json [z0] [dz] [rot0]\n", argv[0]);
        return 2;
    }
    m2b_conf_default(&conf);
    if (argc > 3) conf.z0 = atof(argv[3]);
    if (argc > 4) conf.dz = atof(argv[4]);
    if (argc > 5) conf.rot0 = atof(argv[5]);

    in = fopen(argv[1], "r");
    if (!in) {
        perror(argv[1]);
        return 1;
    }
    if (!fgets(line, sizeof(line), in)) {
        fclose(in);
        return 1;
    }
    while (fgets(line, sizeof(line), in) && n < M2B_RING_CAP) {
        char *p = line, *end;
        acq_frame f;
        memset(&f, 0, sizeof(f));
        if (line[0] == '\n' || line[0] == '\r') {
            continue;
        }
        f.z_mm = strtod(p, &end); p = end;
        if (*p == ',') p++;
        f.pose_rot = (int32_t)strtol(p, &end, 10); p = end;
        if (*p == ',') p++;
        f.t_us = strtod(p, &end); p = end;
        if (*p == ',') p++;
        f.amp = strtod(p, &end); p = end;
        if (*p == ',') p++;
        f.valid = (int)strtol(p, &end, 10);
        /* 11 ms per frame: the measured PL rate, so rate_fps comes out ~90 */
        f.arrive_s = (double)n * 0.011;
        g_ring[n++] = f;
    }
    fclose(in);

    js = m2b_state_json(&conf, g_ring, M2B_RING_CAP, 0, n, n * 0.011 + 0.05);
    out = fopen(argv[2], "w");
    if (!out) {
        perror(argv[2]);
        return 1;
    }
    fputs(js, out);
    fclose(out);
    printf("frames=%d json=%u bytes z0=%.1f dz=%.1f rot0=%.0f\n",
           n, (unsigned)strlen(js), conf.z0, conf.dz, conf.rot0);
    return 0;
}
