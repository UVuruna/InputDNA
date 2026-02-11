# Technical Conclusions - How It All Works

## Overview

This document summarizes our understanding of how MouseMux, browser input, and anti-bot detection actually work at a technical level.

---

## 1. WebSocket Communication is Local

```
Python Worker ──WebSocket──► MouseMux Daemon ──► Chrome Window
                   │
                   ▼
            ws://localhost:41001
```

**Key point:** All communication is 100% local on the machine.

- MouseMux runs a local WebSocket server on port 41001
- No external/internet communication involved
- Latency: < 1ms per message
- Sending 60+ messages per second is trivial for localhost

**Conclusion:** High-frequency path point transmission is not a performance concern.

---

## 2. MouseMux Input Isolation (Claim Mechanism)

Each Chrome window is "claimed" by one virtual mouse. After claiming:

```
┌─────────────────────────────────────────────────────────────┐
│                     MOUSEMUX ROUTING                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Virtual Mouse 1 (hwid=0x3000)                             │
│         │                                                   │
│         └────────► Chrome 1 (Bet365)                       │
│                    └── Only sees events from hwid=0x3000   │
│                                                             │
│  Virtual Mouse 2 (hwid=0x3002)                             │
│         │                                                   │
│         └────────► Chrome 2 (1xBet)                        │
│                    └── Only sees events from hwid=0x3002   │
│                                                             │
│  Virtual Mouse 3 (hwid=0x3004)                             │
│         │                                                   │
│         └────────► Chrome 3 (Stake)                        │
│                    └── Only sees events from hwid=0x3004   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Key points:**
- Each Chrome instance receives input ONLY from its assigned virtual mouse
- Chrome instances are completely unaware of each other
- Input streams are fully isolated
- Parallel operation: all 15 workers can act simultaneously

**Conclusion:** True parallel input — no queue, no conflicts.

---

## 3. What Does a Website Actually See?

### Websites do NOT see:
- ❌ Rendered cursor on screen
- ❌ Visual mouse movement
- ❌ Any graphics or pixels
- ❌ Information about input source (hardware vs virtual)

### Websites DO see:
- ✅ JavaScript events with coordinates and timestamps

```javascript
// This is ALL the website receives:
mousemove: {clientX: 100, clientY: 200, timeStamp: 1707650000123}
mousemove: {clientX: 115, clientY: 218, timeStamp: 1707650000139}
mousemove: {clientX: 134, clientY: 241, timeStamp: 1707650000155}
mousemove: {clientX: 156, clientY: 270, timeStamp: 1707650000171}
...
click:     {clientX: 500, clientY: 400, timeStamp: 1707650000450}
```

**Just an array of (x, y, time) tuples.** Nothing more.

---

## 4. All Mouse Movement is Discrete

There is no such thing as "continuous" mouse movement — not even with real hardware.

### Physical mouse polling rates:

| Mouse Type | Polling Rate | Points per Second | Gap Between Points |
|------------|--------------|-------------------|-------------------|
| Basic USB | 125 Hz | 125 | ~8ms |
| Gaming | 500 Hz | 500 | ~2ms |
| Pro Gaming | 1000 Hz | 1000 | ~1ms |

**Hardware mice send discrete coordinate updates to the OS.**

### Our approach — MATCH your real polling rate:

We don't pick arbitrary values. We **record your actual polling rate** during training:

```python
# From your recorded movements:
your_avg_interval = 8.1ms    # Your mouse reports every ~8ms
your_interval_stddev = 0.4ms # With this much natural variation
your_polling_rate = 123Hz    # Calculated: 1000 / 8.1
```

Then replay **matches exactly**:
- Same average interval as your hardware
- Same timing variation (jitter)
- Website sees identical fingerprint

**Conclusion:** We don't simulate "a mouse" — we simulate YOUR mouse.

---

## 5. What Anti-Bot Systems Actually Analyze

Since websites only receive `(x, y, time)` data, they analyze **patterns in that data**:

### What they CANNOT detect:
| Factor | Why Undetectable |
|--------|------------------|
| Discrete points | All mice are discrete |
| Input source | Browser doesn't report it |
| Virtual vs physical | Indistinguishable at JS level |
| MouseMux | No fingerprint in events |

### What they CAN detect:
| Factor | Bot Signature | Human Signature |
|--------|---------------|-----------------|
| **Path shape** | Perfectly straight lines | Slight curves, corrections |
| **Speed profile** | Constant velocity | Accelerate → cruise → decelerate |
| **Timing intervals** | Perfectly uniform (16.00ms, 16.00ms, 16.00ms) | Variable (14ms, 18ms, 15ms, 17ms) |
| **Overshoot** | None (perfect targeting) | Often overshoots, then corrects |
| **Pre-click pause** | 0ms (instant click) | 50-300ms hesitation |
| **Click duration** | Exactly 50ms every time | Variable (60-150ms) |
| **Micro-jitter** | Perfectly still during hover | Tiny tremor (1-5px) |

---

## 6. Why Our ML Approach Works

```
┌─────────────────────────────────────────────────────────────┐
│                    DETECTION EVASION                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Bot Detection Looks For:     Our ML Model Provides:        │
│  ─────────────────────────    ──────────────────────        │
│                                                             │
│  Straight paths         →     Your personal curved paths    │
│  Constant speed         →     Your acceleration patterns    │
│  Uniform timing         →     Your variable timing          │
│  No overshoot           →     Your overshoot patterns       │
│  Instant clicks         →     Your pre-click hesitation     │
│  Perfect stillness      →     Your micro-jitter             │
│                                                             │
│  ═══════════════════════════════════════════════════════   │
│                                                             │
│  Result: Events indistinguishable from YOUR real input      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

The ML model doesn't generate "generic human" behavior — it generates **YOUR specific behavior** learned from YOUR recorded data.

---

## 7. Data Flow Summary

### Recording Phase (Learning):
```
Your Real Input
      │
      ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   pynput    │────►│  Analyzer   │────►│   SQLite    │
│  listener   │     │  (metrics)  │     │  Database   │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              ▼
                                        Your Personal
                                        Fingerprint Data
```

### Replay Phase (Execution):
```
Robin Worker: "Click at (500, 400)"
      │
      ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    ML       │────►│   Replay    │────►│  MouseMux   │
│  Simulator  │     │   Engine    │     │   (local)   │
└─────────────┘     └─────────────┘     └─────────────┘
      │                   │                   │
 Generates:          Sends via:          Routes to:
 - Path points       WebSocket           Claimed Chrome
 - Timing            localhost:41001     Window
 - Click params
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Output: [(x1,y1,t1), (x2,y2,t2), ...] + click events      │
│                                                             │
│  Indistinguishable from real input because it IS           │
│  your real patterns, just replayed.                        │
└─────────────────────────────────────────────────────────────┘
```

### What Website Receives:
```
┌─────────────────────────────────────────────────────────────┐
│  Chrome (claimed by Virtual Mouse)                         │
│         │                                                   │
│         ▼                                                   │
│  JavaScript Events:                                         │
│  mousemove(115, 218, t+16ms)                               │
│  mousemove(134, 241, t+31ms)   ← Variable timing!          │
│  mousemove(158, 267, t+48ms)                               │
│  mousemove(187, 298, t+63ms)                               │
│  ...                                                        │
│  mousemove(498, 402, t+385ms)  ← Slight overshoot          │
│  mousemove(500, 400, t+412ms)  ← Correction                │
│  [pause 127ms]                  ← Pre-click hesitation     │
│  click(500, 400, t+539ms)                                  │
│         │                                                   │
│         ▼                                                   │
│  Website Analysis: "Looks like normal human input" ✓       │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. Key Technical Conclusions

| Question | Answer |
|----------|--------|
| Is WebSocket communication a bottleneck? | No — localhost, < 1ms latency |
| Can websites detect discrete points? | No — all mice send discrete points |
| Can websites detect MouseMux? | No — events are identical to hardware |
| Can websites detect our simulation? | Not if ML model is well-trained |
| What CAN websites detect? | Unnatural patterns in (x, y, time) data |
| How do we avoid detection? | By replicating YOUR personal patterns |
| Does each Chrome see its own mouse? | Yes — claim mechanism isolates input |
| Can we run 15 workers in parallel? | Yes — truly parallel, no queue needed |

---

## 9. MouseMux Advanced Options (For Reference)

| Option | Purpose | Do We Need It? |
|--------|---------|----------------|
| Enable delta motion | Captures SendInput/SetCursorPos injections | ❌ No — we use WebSocket SDK |
| Enable windows cursor | Uses real Windows cursor vs MouseMux overlay | ⚠️ Maybe for OBS — ask G |

---

## 10. Polling Rate vs FPS — Important Distinction

### Terminology:
| Term | Domain | Meaning |
|------|--------|---------|
| **FPS** | Video/Graphics | Frames rendered per second |
| **Polling Rate** | Input Devices | Coordinate updates per second |

**We must think in polling rate, not FPS.** Mice don't render frames — they report coordinates at their polling rate.

### Can Websites Detect Polling Rate?

**Directly:** ❌ No — JavaScript has no API for this

**Indirectly:** ✅ Yes — by analyzing timestamp gaps:

```javascript
// Website measures:
event1.timeStamp = 1000
event2.timeStamp = 1008   // gap = 8ms → 125Hz
event3.timeStamp = 1016   // gap = 8ms → 125Hz
event4.timeStamp = 1024   // gap = 8ms → 125Hz

// Conclusion: "This user has a 125Hz mouse"
```

### Realistic Polling Rates:

| Polling Rate | Interval | Mouse Type | Risk Level |
|--------------|----------|------------|------------|
| 125 Hz | ~8ms | Basic USB, office mouse | ✅ Safest — most common |
| 250 Hz | ~4ms | Budget gaming | ✅ OK |
| 500 Hz | ~2ms | Gaming mouse | ⚠️ OK, less common |
| 1000 Hz | ~1ms | Pro gaming | ⚠️ Suspicious for casual betting |
| 4000+ Hz | <1ms | Enthusiast | ❌ Very suspicious |

### Critical: Timing Variation

Real mice are NOT perfectly consistent due to USB timing, OS scheduling, etc:

```
Bot signature (bad):     8.00ms, 8.00ms, 8.00ms, 8.00ms, 8.00ms
Human signature (good):  7.8ms, 8.3ms, 7.9ms, 8.1ms, 8.4ms, 7.7ms
```

**Our ML model must capture YOUR actual timing variation from recordings.**

### Best Approach: Record Your Actual Polling Rate

During the recording phase, we measure YOUR real polling rate:

```python
# From recorded data:
intervals = [p2.timestamp - p1.timestamp for p1, p2 in pairs]
your_polling_rate = 1000 / mean(intervals)  # e.g., 125Hz
your_interval_stddev = stddev(intervals)     # e.g., ±0.5ms
```

Then replay uses:
- Your detected polling rate (not assumed)
- Your actual timing variation (not synthetic)

This ensures **100% consistency** with your real hardware.

---

## 11. Recommended Configuration

### MouseMux Settings:
- Mode: **Multiplex all** (visible independent cursors)
- SDK: **Web SDK enabled** on port 41001
- Max users: **24** (supports 15 workers + buffer)

### Our Replay Settings:
- Polling rate: **Match your recorded rate** (typically 125Hz = ~8ms)
- Timing variation: **From your recorded data** (typically ±0.3-0.5ms stddev)
- Path shape: **ML-generated** (your personal curves)

### Why Match Your Real Polling Rate:
- Consistent with your actual hardware fingerprint
- Anti-bot systems may flag mismatched rates
- Your timing variation is already captured in training data
- No need to guess — we have the real data

---

## Summary

The entire system works because:

1. **MouseMux** provides true input isolation per Chrome window
2. **Websites only see (x, y, time)** — not visuals, not source
3. **All mice are discrete** — our approach is physically identical
4. **We match YOUR polling rate** — not generic values, YOUR hardware fingerprint
5. **ML model replicates YOUR patterns** — path, speed, timing, everything
6. **Local WebSocket** — no performance concerns at any frequency

What makes input "human" is not the mechanism of delivery, but the **statistical properties of the coordinate/timing data**. Our system ensures:
- Path shapes match YOUR curves
- Speed profiles match YOUR acceleration patterns  
- Timing intervals match YOUR polling rate + variation
- Click behavior matches YOUR hesitation and duration

The result is input that is statistically indistinguishable from YOUR real input — because it's trained on YOUR real data and replayed with YOUR hardware characteristics.
