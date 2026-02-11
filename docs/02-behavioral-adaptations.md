# Behavioral Adaptations for Human-Like Mouse Simulation

## Purpose

This document details the **behavioral patterns** that distinguish real human mouse usage from bot/automation. Each pattern is something we need to capture, analyze, and eventually replicate.

Understanding *why* these behaviors exist helps us capture them correctly and replay them convincingly.

---

## 1. Pre-Click Hesitation

### What it is
The small pause (50-500ms) that occurs after you reach a target but before you click.

### Why humans do it
- Visual confirmation ("Is this the right button?")
- Decision finalization
- Motor preparation for click action
- Sometimes reading/scanning the element

### What to capture
- Duration of hover before click
- Whether duration varies by target size
- Whether it varies by familiarity (repeated actions faster?)

### How bots fail
Bots typically click instantly upon reaching target (0ms delay) — this is a major detection signal.

### Replay strategy
Add variable delay based on your recorded distribution. Short movements to familiar targets = shorter hesitation.

---

## 2. Click Duration (Press Time)

### What it is
Time between mouse button down and mouse button up.

### Typical human range
- Fast click: 50-80ms
- Normal click: 80-150ms  
- Deliberate click: 150-300ms

### Personal variation
Everyone has their own click "signature":
- Some people click fast and light
- Some press firmly and longer
- Fatigue increases press time

### What to capture
- Press duration for each click type (left, right, middle)
- Correlation with movement speed before click
- Time-of-day patterns

### How bots fail
- Perfectly consistent click times (exactly 100ms every time)
- Unrealistically fast (<30ms)
- No variation in distribution

---

## 3. Post-Click Behavior

### What it is
What happens in the 0-500ms after releasing a click.

### Three common patterns

**A) Immediate departure**
- Click → immediately start moving to next target
- Common in fast, confident actions

**B) Momentary pause**
- Click → stay still for 100-300ms → then move
- Common when waiting for UI response

**C) Recoil movement**
- Click → tiny backward/random movement (2-10px)
- Physical reaction to click force
- Very human, very subtle

### What to capture
- Time until next movement starts
- Direction and magnitude of any recoil
- Correlation with click force (press duration)

### How bots fail
Bots almost never have recoil. They either stay perfectly still or immediately move in an obviously intentional direction.

---

## 4. Overshoot & Correction

### What it is
Moving past the intended target, then correcting back to it.

### Why it happens
- Ballistic movement phase overshoots
- Fine motor correction brings cursor back
- More common with:
  - Fast movements
  - Small targets
  - Fatigue

### The biomechanics
Human movement has two phases:
1. **Ballistic phase**: Fast, pre-programmed, imprecise
2. **Correction phase**: Slow, feedback-driven, precise

### What to capture
- Frequency of overshoots (what % of movements?)
- Overshoot distance (typically 5-30px)
- Correction time (how long to get back on target)
- Correlation with movement speed/distance

### How bots fail
Basic Bézier curves don't overshoot — they smoothly arrive at target. This is a tell.

### Detection pattern
```
Movement ends → cursor position → small reverse movement → click
```
This pattern should be flagged and stored separately.

---

## 5. Micro-Jitter While Hovering

### What it is
Tiny involuntary movements (1-5px) while trying to hold the cursor still.

### Why it happens
- Hand tremor (everyone has it)
- Muscle micro-adjustments
- Heartbeat (yes, really)
- Breathing

### Characteristics
- Amplitude: 1-5px typically
- Frequency: somewhat random, 2-10 movements per second
- Pattern: roughly circular/random, not linear

### What to capture
- Jitter amplitude (standard deviation of positions)
- Jitter frequency
- Duration of hover periods with jitter
- Your personal jitter signature

### How bots fail
Bots are perfectly still when not moving. Zero jitter = inhuman.

### Replay strategy
Add Perlin noise or recorded jitter patterns during any "hover" or "wait" period.

---

## 6. Movement Sequences (Chains)

### What it is
The relationship between consecutive movements. Mouse actions don't happen in isolation — they're part of workflows.

### Common patterns

**Form filling:**
```
Field 1 → Field 2 → Field 3 → Submit button
```
Predictable sequence, similar angles, consistent rhythm.

**Menu navigation:**
```
Menu button → Dropdown item → Submenu item
```
Short pauses between, specific directional patterns.

**Reading/scanning:**
```
Irregular movements following eye gaze
```
Often horizontal sweeps, variable speed.

### What to capture
- Link each movement to previous movement
- Time gap between movements
- Angle change from previous movement
- Speed change from previous movement

### Analysis potential
Find YOUR common sequences:
- How you navigate specific UI patterns
- Your rhythm for form filling
- Your scanning patterns

---

## 7. Drag Operations

### What it is
Click-and-hold while moving, then release. Used for:
- Sliders
- Drag-and-drop
- Text selection
- Scrollbar dragging
- Window resizing

### Characteristics
- Usually slower than regular movement
- More linear (deliberate control)
- Often has micro-corrections
- Release timing varies

### What to capture
- Drag path (separate from regular movements)
- Speed profile during drag
- Precision at release point
- Duration of hold before drag starts

### Why it matters
Drag behavior is distinctly different from point-and-click. Bots often handle drags poorly or skip them entirely.

---

## 8. Scroll Behavior

### What it is
Mouse wheel or trackpad scroll patterns.

### Personal patterns
- Scroll amount per "tick"
- Speed of consecutive scrolls
- Pause-scroll-pause rhythm
- Position preference (where cursor rests while scrolling)

### What to capture
- Scroll direction and delta
- Cursor position during scroll
- Time between scroll events
- Relationship to reading speed

### Bot detection
- Perfectly even scroll amounts
- Unrealistic scroll speed
- Scrolling while cursor is in unusual position

---

## 9. Fatigue Patterns

### What it is
How your mouse behavior changes over time.

### Observable changes
- **Speed decreases**: Movements get slower
- **Precision decreases**: More overshoots, more corrections
- **Click duration increases**: Slower clicks
- **Pause times increase**: Longer hesitations
- **Jitter increases**: Hand less steady

### What to capture
- Recording session duration at time of each movement
- Aggregate metrics per hour of recording
- Time of day (morning vs evening patterns)

### Replay application
If simulating extended sessions, gradually introduce fatigue characteristics.

---

## 10. Keyboard → Mouse Transition

### What it is
The timing and behavior when switching from keyboard to mouse.

### The physical action
1. Hands on keyboard
2. Move hand to mouse
3. Grab mouse
4. First movement

### What to capture
- Time since last keypress when mouse movement starts
- Characteristics of "first grab" movements
- Are they different from mid-session movements?

### Why it matters
Bots often don't use keyboard at all, or switch instantly with no transition time. The "reach for mouse" delay is human.

### Typical timing
- Fast typist, mouse nearby: 200-500ms
- Mouse farther away: 500-1000ms
- Varies by individual setup

---

## 11. Target Size Adaptation

### What it is
How movement characteristics change based on target size.

### Fitts's Law
Movement time = a + b × log₂(Distance/Width + 1)

Larger targets = faster, less precise movements
Smaller targets = slower, more careful movements

### What to capture (if possible)
This is harder without knowing what's on screen, but we can infer:
- Movements ending in precise small corrections = small target
- Movements ending confidently = large target
- Pre-click jitter pattern differences

### Pattern inference
Even without screen data, clustering movements by their end-phase characteristics can reveal target size patterns.

---

## 12. Directional Bias

### What it is
Personal tendencies in movement direction and curvature.

### Common biases
- **Handedness effect**: Right-handers often curve slightly clockwise
- **Wrist pivot**: Creates arc patterns
- **Preferred quadrants**: Some screen areas feel more natural

### What to capture
- Direction angle distribution
- Curvature direction (left vs right curve)
- Speed by direction (often faster moving toward dominant hand side)

### Replay application
Maintain your personal directional biases instead of randomly varying curvature direction.

---

## Summary: Detection Signals We're Countering

| Bot Tell | Human Behavior | Our Solution |
|----------|----------------|--------------|
| Instant clicks | Pre-click hesitation | Record & replay pause distribution |
| Perfect click timing | Variable press duration | Record personal click signature |
| No post-click movement | Recoil & pause patterns | Capture post-click behavior |
| Smooth arrival at target | Overshoot & correction | Detect and replicate overshoots |
| Perfect stillness | Micro-jitter | Add recorded jitter patterns |
| Isolated movements | Sequential chains | Link movements, replay chains |
| Consistent speed | Fatigue variation | Track time-based changes |
| No keyboard correlation | Natural transitions | Capture keyboard→mouse timing |
| Random curvature | Personal directional bias | Learn individual curve preferences |

---

## Data Priority

### Must Have (Phase 1)
1. Pre-click hesitation
2. Click duration
3. Basic overshoot detection
4. Movement chaining

### Should Have (Phase 2)
5. Post-click behavior
6. Micro-jitter measurement
7. Scroll patterns
8. Keyboard timing

### Nice to Have (Phase 3)
9. Fatigue analysis
10. Drag operations
11. Directional bias analysis
12. Target size inference
