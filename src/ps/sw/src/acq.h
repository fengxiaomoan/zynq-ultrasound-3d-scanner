/* AXI frame reader for the M2b PS firmware.
 *
 * The PL side (fpga/ps/acq_axi_regs.v) publishes one 176-bit record per frame at
 * 0x4000_0000 and raises a pending flag; the PS reads the record and writes 1 to
 * 0x20 to acknowledge it.  This file is the only place that knows the register
 * map, so a later RTL change has one place to touch.
 *
 * Coherence: the read side latches the payload atomically, but a *new* frame can
 * land in the middle of our 7-register read sequence.  We therefore read SEQ,
 * then the payload, then SEQ again and only accept (and ACK) the record when the
 * two SEQs agree.  ACK is never issued for a record we did not read, so a frame
 * cannot be swallowed by an early acknowledge.
 */
#ifndef M2B_ACQ_H
#define M2B_ACQ_H

#include <stdint.h>

#define ACQ_BASE        0x40000000u

#define ACQ_STATUS      0x00u   /* [0] pending [1] missed [15:8] missed_cnt [31:16] seq */
#define ACQ_SEQ         0x04u
#define ACQ_PEAK_LO     0x08u
#define ACQ_PEAK_HI     0x0Cu
#define ACQ_CENT_LO     0x10u
#define ACQ_CENT_HI     0x14u
#define ACQ_POSE_ROT    0x18u
#define ACQ_POSE_LIFT   0x1Cu
#define ACQ_ACK         0x20u   /* write 1: clear pending */
#define ACQ_CTRL        0x24u   /* bit0 arm, bit16 sel_ext */
#define ACQ_PERIOD_MS   0x28u

/* ---- F1 pose window (M3 image only; reads 0 on M2b) ----------------------
 * 128-bit pose word, refreshed at 1 kHz by the PL independently of the frame
 * record: {magic 0x4D50, seq[7:0], flags[7:0], tick[31:0], roll[15:0],
 *          pitch[15:0], yaw[15:0], err_cnt[15:0]}
 * Angles are counts with 90 deg = 16384 (0.005493 deg/LSB).  Coherent read:
 * header, payload, header again; the two headers must be identical. */
#define ACQ_F1_POSE_LO  0x30u   /* {yaw[15:0], err_cnt[15:0]}   */
#define ACQ_F1_POSE_MID 0x34u   /* {roll[15:0], pitch[15:0]}    */
#define ACQ_F1_TICK     0x38u   /* 50 MHz tick at sample time   */
#define ACQ_F1_HDR      0x3Cu   /* {magic, seq[7:0], flags[7:0]} */
#define ACQ_F1_MAGIC    0x4D50u
#define ACQ_F1_TICK_HZ  50000000.0
#define ACQ_F1_CPD      (16384.0 / 90.0)   /* counts per degree */

typedef struct {
    uint32_t seq;        /* the record's own 16-bit sequence, 0-based */
    int32_t  pose_rot;   /* commanded rotation counter at capture_start */
    int32_t  pose_lift;
    uint64_t peak_word;  /* {valid, frame[12:0], idx[9:0], amp[15:0]} */
    uint64_t cent_word;  /* {valid, idx[9:0], sum_w[17:0], sum_kw[26:0]} */
    double   t_us;       /* centroid when valid, else peak idx, * 0.2 us */
    double   amp;        /* the 40-bit word's amplitude (16 bit) */
    int      valid;      /* centroid valid when it exists, else the peak valid */
    int      cvalid;     /* centroid word valid (page colours by this) */
    uint32_t idx;        /* peak idx */
    uint32_t cidx;       /* centroid idx */
    int      gap;        /* 1 = the sequence jumped before this frame */
    double   arrive_s;   /* XTime seconds when the PS read it */
    double   z_mm;       /* layer height assigned by the caller */
} acq_frame;

/* One coherent attitude sample.  "ok" is the PL's valid flag, not a judgement
 * about the operator: it is 0 while the MPU6050 is still starting up or the only
 * sensor is missing, and the page then falls back to its own auto-spin. */
typedef struct {
    int      ok;          /* flags bit0: pose valid */
    int      init;        /* flags bit1: 32-sample warm-up done (accel only before) */
    int      i2c_err;     /* flags bit2: NACK/timeout seen  */
    int      stuck;       /* flags bit3: the I2C master had to recover the bus */
    uint8_t  seq;
    uint8_t  flags;
    uint16_t err_cnt;
    uint32_t tick;        /* PL 50 MHz tick at the sample */
    double   tick_ms;     /* tick converted to ms since PL reset */
    double   age_ms;      /* PS-observed age of this sample (see acq_read_pose) */
    int16_t  roll, pitch, yaw;   /* counts, 90 deg = 16384 */
    uint32_t n;           /* samples accepted since boot */
} acq_pose;

void     acq_init(uint16_t period_ms);
void     acq_arm(int on);
int      acq_armed(void);
int      acq_read(acq_frame *f);          /* 1 = a new, coherent record */
uint32_t acq_missed(void);                /* cumulative since the last arm */
uint32_t acq_status(void);
double   acq_now_s(void);

/* 1 = a coherent pose sample was read (the values are then also copied to *p).
 * Returns 0 when the F1 block is absent (magic mismatch) or the read was torn.
 *
 * age_ms is measured on the PS side, not by the PL: it is the time since this
 * sequence number was first observed.  With a ~2 ms poll it under-reads the true
 * age by at most one poll interval; the exact PL timestamp is in tick_ms, so a
 * later E3 analysis can use that instead. */
int      acq_read_pose(acq_pose *p);
double   acq_pose_deg(int16_t counts);

#endif /* M2B_ACQ_H */
