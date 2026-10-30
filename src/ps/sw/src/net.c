#include "net.h"

#include <stdio.h>
#include <string.h>

#include "lwip/init.h"
#include "lwip/tcp.h"
#include "lwip/ip_addr.h"
#include "netif/xadapter.h"
#include "xil_exception.h"
#include "xscugic.h"
#include "netif/xemacpsif.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xparameters.h"

#include "page_html.h"

#ifndef XPAR_XEMACPS_0_BASEADDR
#error "xparameters.h has no XPAR_XEMACPS_0_BASEADDR -- regenerate the BSP from ps_m2.xsa"
#endif

#define M2B_IP0 192
#define M2B_IP1 168
#define M2B_IP2 1
#define M2B_IP3 10

#define RECV_CAP 1400

/* connection phases */
enum { PH_RECV = 0, PH_HDR, PH_BODY, PH_DRAIN, PH_IDLE };

static struct netif g_netif;
static XScuGic       g_gic;
static net_hooks     g_hooks;
static char          g_ip[20];

static struct tcp_pcb *g_pcb;
static unsigned g_conn_age;     /* net_poll ticks since the current connection progressed */
static int    g_phase = PH_IDLE;
static char   g_req[RECV_CAP];
static int    g_req_len;

static char   g_hdr[256];
static int    g_hdr_len;
static int    g_hdr_off;
static const char *g_body;
static size_t g_body_len;
static size_t g_body_sent;
static size_t g_acked;

static const char *status_text(int code)
{
    switch (code) {
    case 200: return "OK";
    case 400: return "Bad Request";
    case 404: return "Not Found";
    default:  return "Error";
    }
}

static void forget_pcb(void)
{
    if (g_pcb) {
        tcp_arg(g_pcb, NULL);
        tcp_recv(g_pcb, NULL);
        tcp_sent(g_pcb, NULL);
        tcp_err(g_pcb, NULL);
    }
    g_pcb = NULL;
    g_phase = PH_IDLE;
    g_req_len = 0;
    g_hdr_len = g_hdr_off = 0;
    g_body = NULL;
    g_body_len = g_body_sent = g_acked = 0;
}

static void conn_abort(void)
{
    if (g_pcb) {
        tcp_abort(g_pcb);
    }
    forget_pcb();
}

static void start_response(int code, const char *ctype, const char *body, size_t len)
{
    g_hdr_len = snprintf(g_hdr, sizeof(g_hdr),
                         "HTTP/1.0 %d %s\r\nContent-Type: %s\r\n"
                         "Cache-Control: no-store\r\nContent-Length: %u\r\n"
                         "Connection: close\r\n\r\n",
                         code, status_text(code), ctype, (unsigned)len);
    if (g_hdr_len < 0 || g_hdr_len > (int)sizeof(g_hdr)) {
        g_hdr_len = 0;
    }
    g_hdr_off = 0;
    g_body = body;
    g_body_len = len;
    g_body_sent = 0;
    g_acked = 0;
    g_phase = PH_HDR;
}

static void send_more(void)
{
    while (g_pcb) {
        u16_t space = tcp_sndbuf(g_pcb);

        if (space == 0) {
            return;
        }
        if (g_phase == PH_HDR) {
            int rem = g_hdr_len - g_hdr_off;
            if (rem <= 0) {
                g_phase = PH_BODY;
                continue;
            }
            if ((int)space < rem) {
                return;          /* cannot split the header; wait for room */
            }
            {
                err_t e = tcp_write(g_pcb, g_hdr + g_hdr_off, (u16_t)rem,
                                    TCP_WRITE_FLAG_COPY);
                if (e == ERR_MEM) {
                    return;      /* send buffer full: retry from on_sent() */
                }
                if (e != ERR_OK) {
                    conn_abort();
                    return;
                }
            }
            g_hdr_off = g_hdr_len;
            tcp_output(g_pcb);
            continue;
        }
        if (g_phase == PH_BODY) {
            size_t rem = g_body_len - g_body_sent;
            u16_t n;
            if (rem == 0) {
                g_phase = PH_DRAIN;
                continue;
            }
            n = (rem > space) ? space : (u16_t)rem;
            if (n > 2920) {
                n = 2920;
            }
            {
                err_t e = tcp_write(g_pcb, g_body + g_body_sent, n,
                                    TCP_WRITE_FLAG_COPY);
                if (e == ERR_MEM) {
                    return;      /* send buffer full: retry from on_sent() */
                }
                if (e != ERR_OK) {
                    conn_abort();
                    return;
                }
            }
            g_body_sent += n;
            tcp_output(g_pcb);
            continue;
        }
        return;                  /* PH_DRAIN: wait for the sent callback */
    }
}

static void try_close(void)
{
    size_t total = (size_t)g_hdr_len + g_body_len;
    if (g_phase == PH_DRAIN && g_acked >= total) {
        struct tcp_pcb *pcb = g_pcb;
        forget_pcb();
        tcp_close(pcb);
    }
}

static err_t on_sent(void *arg, struct tcp_pcb *pcb, u16_t len)
{
    g_conn_age = 0;
    (void)arg;
    (void)pcb;
    g_acked += len;
    try_close();
    return ERR_OK;
}

static void on_err(void *arg, err_t err)
{
    (void)arg;
    (void)err;
    forget_pcb();                /* lwIP already freed the pcb */
}

static void dispatch(char *req)
{
    char *sp1 = strchr(req, ' ');
    char *path = sp1 ? sp1 + 1 : NULL;
    char *sp2 = path ? strchr(path, ' ') : NULL;

    if (!sp1 || !path || !sp2) {
        start_response(400, "text/plain", "bad request", 11);
        return;
    }
    *sp2 = '\0';
    {
        char *q = strchr(path, '?');
        if (q) {
            *q++ = '\0';
        }
        if (strcmp(path, "/") == 0 || strcmp(path, "/index.html") == 0) {
            start_response(200, "text/html; charset=utf-8", PAGE_HTML,
                           sizeof(PAGE_HTML) - 1);
        } else if (strcmp(path, "/state") == 0) {
            const char *js = g_hooks.state_json ? g_hooks.state_json() : "{}";
            start_response(200, "application/json; charset=utf-8", js, strlen(js));
        } else if (strcmp(path, "/api/pose") == 0) {
            /* F1: deliberately its own route.  /state is 60-120 KB and cached for
             * 400 ms; the attitude is wanted at 20 Hz, so it gets a ~180 B body
             * that is cheap to rebuild on every request. */
            const char *js = g_hooks.pose_json ? g_hooks.pose_json() : "{\"ok\":0}";
            start_response(200, "application/json; charset=utf-8", js, strlen(js));
        } else if (strcmp(path, "/api/status") == 0) {
            start_response(200, "application/json; charset=utf-8",
                           "{\"ok\":true}", 11);
        } else if (strcmp(path, "/api/config") == 0 ||
                   strcmp(path, "/api/arm") == 0 ||
                   strcmp(path, "/api/ref") == 0) {
            int ok = g_hooks.command ? g_hooks.command(path, q ? q : "") : 0;
            if (ok) {
                start_response(200, "application/json; charset=utf-8",
                               "{\"ok\":true}", 11);
            } else {
                start_response(400, "text/plain", "bad parameters", 14);
            }
        } else {
            start_response(404, "text/plain", "not found", 9);
        }
    }
}

static err_t on_recv(void *arg, struct tcp_pcb *pcb, struct pbuf *p, err_t err)
{
    g_conn_age = 0;
    (void)arg;
    if (err != ERR_OK) {
        if (p) {
            pbuf_free(p);
        }
        return err;
    }
    if (!p) {
        /* remote closed before finishing: nothing left to send to */
        if (g_phase == PH_RECV || g_phase == PH_IDLE) {
            forget_pcb();
            tcp_close(pcb);
        }
        return ERR_OK;
    }
    tcp_recved(pcb, p->tot_len);
    {
        struct pbuf *q = p;
        while (q && g_req_len < RECV_CAP - 1) {
            u16_t n = q->len;
            if ((int)n > RECV_CAP - 1 - g_req_len) {
                n = (u16_t)(RECV_CAP - 1 - g_req_len);
            }
            memcpy(g_req + g_req_len, q->payload, n);
            g_req_len += n;
            q = q->next;
        }
    }
    pbuf_free(p);
    g_req[g_req_len] = '\0';

    if (g_phase == PH_RECV &&
        (strstr(g_req, "\r\n\r\n") || strstr(g_req, "\n\n"))) {
        dispatch(g_req);
        send_more();
        if (g_phase == PH_DRAIN) {
            try_close();
        }
    }
    return ERR_OK;
}

static err_t on_accept(void *arg, struct tcp_pcb *pcb, err_t err)
{
    (void)arg;
    if (err != ERR_OK) {
        return ERR_VAL;
    }
    if (g_pcb) {
        /* One client at a time.  While the current connection is making
         * progress, refuse the newcomer: aborting a connection mid-response
         * truncated /state, which is why the page only rendered on some
         * refreshes (2026-10-27).  But a client that vanished mid-send would
         * otherwise lock everyone out forever, so one that has made no progress
         * for ~3 s gets kicked. */
        if (g_conn_age < 300u) {
            tcp_abort(pcb);
            return ERR_ABRT;
        }
        conn_abort();
    }
    g_conn_age = 0;
    forget_pcb();
    g_pcb = pcb;
    g_phase = PH_RECV;
    g_req_len = 0;
    tcp_setprio(pcb, TCP_PRIO_NORMAL);
    tcp_arg(pcb, NULL);
    tcp_recv(pcb, on_recv);
    tcp_sent(pcb, on_sent);
    tcp_err(pcb, on_err);
    return ERR_OK;
}

/* ---- GIC CPU interface (GICC) ---------------------------------------------
 * Zynq GIC-400: distributor at 0xF8F01000, CPU interface at 0xF8F00100.
 * These are the only two registers that matter for "is the CPU willing to take
 * the EMAC IRQ 54": GICC_CTLR bit0 (enable) and GICC_PMR (priority mask, 0
 * masks everything).  Both are banked per CPU, so the CPU itself has to write
 * them -- JTAG cannot (it gets "Banked register should be accessed from a CPU").
 */
#define M2B_GICC_CTLR 0xF8F00100u
#define M2B_GICC_PMR  0xF8F00104u
#define M2B_GICC_BPR  0xF8F00108u
#define M2B_GICD_CTLR 0xF8F01000u
#define M2B_GEM_ISR   0xE000B024u

static void gic_barrier(void)
{
    __asm__ volatile ("dsb" ::: "memory");
    __asm__ volatile ("isb" ::: "memory");
}

static int gic_cpu_if_ok(void)
{
    return ((Xil_In32(M2B_GICC_CTLR) & 0x1u) != 0u) &&
           (Xil_In32(M2B_GICC_PMR) != 0u);
}

/* Force the CPU interface on and verify.  Returns 0 when the readback proves it
 * is enabled, -1 otherwise.  Cheap enough to call from net_poll(). */
static int gic_cpu_if_enable(int tries)
{
    int i = 0;
    while (i++ < tries) {
        if (gic_cpu_if_ok()) {
            return 0;
        }
        Xil_Out32(M2B_GICC_PMR, 0xFFu);   /* allow every priority */
        Xil_Out32(M2B_GICC_BPR, 0x00u);
        Xil_Out32(M2B_GICC_CTLR, 0x01u);  /* EnableGrp0 */
        Xil_Out32(M2B_GICD_CTLR, 0x01u);  /* distributor (normally already 1) */
        gic_barrier();
    }
    return gic_cpu_if_ok() ? 0 : -1;
}

static unsigned g_gic_div;      /* net_poll() calls since the last check */
static unsigned g_gic_stuck;    /* consecutive checks that saw pending RX */
static unsigned g_gic_rescues;  /* how many times the watchdog fired */

/* ---- polled RX -------------------------------------------------------------
 * The Xilinx port fills lwIP's recv_q from the MAC interrupt handler; nothing
 * else drains the RX descriptors.  On this board the GIC's delivery of IRQ 54
 * has been unreliable (see the GICC code above), and when it is not delivered
 * the whole network silently dies while the CPU keeps running.
 *
 * So we drive the very same handler from the main loop and mask the MAC's own
 * interrupt output: the status bits are untouched, so the handler behaves
 * identically, but delivery no longer depends on the GIC at all.  One register
 * read per net_poll() when idle.
 */
static XEmacPs *g_emacps;

static void rx_poll_init(void)
{
    struct xemac_s *emac = (struct xemac_s *)g_netif.state;
    if (emac == NULL || emac->type != xemac_type_emacps || emac->state == NULL) {
        return;
    }
    g_emacps = &((xemacpsif_s *)emac->state)->emacps;
    /* Keep the MAC generating status, but stop the GIC from delivering IRQ 54:
     * disable it at the distributor (ICENABLER1 bit 22) and enable every MAC
     * interrupt so the status bits the handler looks at are actually set. */
    Xil_Out32(0xF8F01184u, (1u << 22));
    Xil_Out32(0xE000B028u, 0xFFFFFFFFu);
}

#ifdef M2B_NET_DEBUG
/* Temporary bring-up counters.  They live in the strongly-ordered AXI GPIO so
 *   ch1 = (frames_to_lwip << 16) | arp_frames
 *   ch2 = (linkoutput_calls << 16) | ip_frames
 */
static volatile unsigned g_dbg_rx, g_dbg_arp, g_dbg_ip, g_dbg_tx;
static err_t (*g_dbg_orig_linkoutput)(struct netif *, struct pbuf *);

static void dbg_publish(void)
{
    Xil_Out32(0x41200000u, (g_dbg_rx << 16) | g_dbg_arp);
    Xil_Out32(0x41200008u, (g_dbg_tx << 16) | g_dbg_ip);
}

static err_t dbg_linkoutput(struct netif *n, struct pbuf *p)
{
    g_dbg_tx++;
    dbg_publish();
    return g_dbg_orig_linkoutput(n, p);
}

static err_t dbg_input(struct pbuf *p, struct netif *netif)
{
    const unsigned char *f = (const unsigned char *)p->payload;
    unsigned type = (p->len >= 14) ? ((unsigned)f[12] << 8 | f[13]) : 0;
    g_dbg_rx++;
    if (type == 0x0806u) {
        g_dbg_arp++;
    } else if (type == 0x0800u) {
        g_dbg_ip++;
    }
    dbg_publish();
    return ethernet_input(p, netif);
}
#endif

void net_init(const net_hooks *hooks, unsigned char last_mac_byte)
{
    ip_addr_t ipaddr, netmask, gw;
    unsigned char mac[6] = {0x00, 0x0a, 0x35, 0x00, 0x01, last_mac_byte};
    struct tcp_pcb *l;

    g_hooks = *hooks;
    forget_pcb();
    snprintf(g_ip, sizeof(g_ip), "%d.%d.%d.%d", M2B_IP0, M2B_IP1, M2B_IP2, M2B_IP3);

    lwip_init();

    /* GIC: make sure the CPU interface is actually ON, and prove it.
     *
     * Without this the MAC's "frame received" interrupt is never taken: the
     * distributor shows IRQ 54 enabled and targeted at CPU0, the MAC shows ISR
     * pending, RX descriptors pile up, and lwIP's recv_q stays empty -- no ARP
     * reply, no ping, no page (measured 2026-10-27).  The driver's
     * XScuGic_CfgInitialize() fixed it twice and silently did nothing other
     * times, so: initialise, then write the GICC registers ourselves and verify
     * by readback, retrying for a bounded time.  If verification still fails we
     * keep going (the stack is still useful) and net_poll() retries at runtime. */
    {
        XScuGic_Config *gic_cfg = XScuGic_LookupConfig(XPAR_XSCUGIC_0_BASEADDR);
        if (gic_cfg != NULL) {
            XScuGic_CfgInitialize(&g_gic, gic_cfg, gic_cfg->CpuBaseAddress);
        }
        (void)gic_cpu_if_enable(8);
    }

    IP4_ADDR(&ipaddr, M2B_IP0, M2B_IP1, M2B_IP2, M2B_IP3);
    IP4_ADDR(&netmask, 255, 255, 255, 0);
    IP4_ADDR(&gw, M2B_IP0, M2B_IP1, M2B_IP2, 1);
    if (!xemac_add(&g_netif, &ipaddr, &netmask, &gw, mac, XPAR_XEMACPS_0_BASEADDR)) {
        xil_printf("net: xemac_add failed\r\n");
        return;
    }
    netif_set_default(&g_netif);
    netif_set_up(&g_netif);
    rx_poll_init();
#ifdef M2B_NET_DEBUG
    g_dbg_orig_linkoutput = g_netif.linkoutput;
    g_netif.linkoutput = dbg_linkoutput;
    g_netif.input = dbg_input;
    Xil_Out32(0x41200000u, 0xDEAD0001u);   /* reached this point */
    Xil_Out32(0x41200008u, 0xDEAD0002u);
#endif

    l = tcp_new();
    if (!l) {
        xil_printf("net: tcp_new failed\r\n");
        return;
    }
    if (tcp_bind(l, IP_ADDR_ANY, 80) != ERR_OK) {
        xil_printf("net: tcp_bind failed\r\n");
        tcp_close(l);
        return;
    }
    l = tcp_listen(l);
    if (!l) {
        xil_printf("net: tcp_listen failed\r\n");
        return;
    }
    tcp_accept(l, on_accept);

    /* The SDT BSP's XSetupInterruptSystem programs the GIC distributor (IRQ 54
     * enabled, targeted at CPU0) but the CPU interface is left disabled, so the
     * MAC's "frame received" interrupt is never taken: on 2026-10-27 the MAC
     * showed ISR pending + IMR unmasked, RX descriptors piled up with the NEW
     * bit set, and lwIP's recv_q stayed empty (no ARP reply, ping dead).
     * Enabling the CPU interface here makes the RX interrupt reach
     * XEmacPs_IntrHandler, which is what fills recv_q. */
    (void)gic_cpu_if_enable(8);
#ifdef M2B_NET_DEBUG
    /* Publish the verdict so JTAG can read it even though GICC is unreadable
     * from the debugger (banked):  ch2 = (CTLR << 16) | PMR,
     * ch1 = 0xC0DE | ok<<2 (written last, overrides the DEAD marker). */
    {
        u32 ctlr = Xil_In32(M2B_GICC_CTLR);
        u32 pmr  = Xil_In32(M2B_GICC_PMR);
        u32 isr  = Xil_In32(M2B_GEM_ISR);
        Xil_Out32(0x41200008u, ((ctlr & 0xFFFFu) << 16) | (pmr & 0xFFFFu));
        Xil_Out32(0x41200000u, 0xC0DE0000u | ((ctlr & 1u) << 2) | (pmr ? 2u : 0u) |
                               ((isr & 1u) << 4));
    }
#endif

    Xil_ExceptionEnable();
    xil_printf("net: http://%s/\r\n", g_ip);
}

void net_poll(void)
{
    if (g_pcb) { g_conn_age++; } else { g_conn_age = 0; }

    if (g_emacps) {
        XEmacPs_IntrHandler(g_emacps);   /* polled RX/TX completion */
    }
    if (g_netif.input) {
        xemacif_input(&g_netif);
    }

    /* Runtime watchdog for the GIC CPU interface.  The MAC's ISR bits are
     * cleared by its interrupt handler; if "frame received"/"rx used" are still
     * pending ~1 s apart, the handler is not running and nothing will drain the
     * RX path -- so force the CPU interface on again.  Two consecutive bad
     * samples (not one) so a frame arriving exactly at sample time cannot
     * trigger it.  ~100 net_poll() calls is about one second at 90 fps. */
    if (++g_gic_div >= 100u) {
        g_gic_div = 0;
        if ((Xil_In32(M2B_GEM_ISR) & 0x06u) != 0u) {
            if (++g_gic_stuck >= 2u) {
                if (gic_cpu_if_enable(3) == 0) {
                    g_gic_rescues++;
                }
                g_gic_stuck = 0;
            }
        } else {
            g_gic_stuck = 0;
        }
    }

    if (g_pcb && g_phase != PH_IDLE && g_phase != PH_RECV) {
        send_more();
    }
}

const char *net_ip_string(void) { return g_ip; }
