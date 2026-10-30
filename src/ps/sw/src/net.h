/* Minimal HTTP/1.0 server on lwIP's raw API (NO_SYS).
 *
 * Why not lwIP's httpd: lwIP 2.2.0 dropped the old httpd app, and the page needs
 * one dynamic resource (/state, up to ~100 KB) plus runtime parameters.  A
 * ~200-line raw-API server with one connection at a time is easier to verify
 * than a file system plus SSI/FS data.
 *
 * Routes
 *   GET /                 the live model page (src/page_html.h)
 *   GET /state            the JSON built by model.c
 *   GET /api/pose         tiny pose JSON (F1): polled at 50 ms by the page
 *   GET /api/config?...   z0, dz, rot0, period, plan_layers
 *   GET /api/arm?on=1|0   arm/disarm the PL frame trigger
 *   GET /api/status       tiny liveness JSON (works even when the ring is empty)
 */
#ifndef M2B_NET_H
#define M2B_NET_H

#include <stddef.h>

typedef struct {
    const char *(*state_json)(void);
    /* F1: a small object (~180 B) that must NOT be folded into /state, because
     * /state is 60-120 KB and cached for 400 ms while the pose is wanted at
     * 20 Hz.  Optional: NULL answers {"ok":0}. */
    const char *(*pose_json)(void);
    /* returns 0 when the query is not understood */
    int (*command)(const char *path, const char *query);
} net_hooks;

void net_init(const net_hooks *hooks, unsigned char last_mac_byte);
void net_poll(void);
const char *net_ip_string(void);

#endif /* M2B_NET_H */
