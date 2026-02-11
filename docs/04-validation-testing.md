# Validation & Similarity Testing Framework

## Overview

After the ML model is trained on your personal input patterns, we need a way to **validate** how accurately it can simulate you. This framework runs in "shadow mode" — comparing model predictions against your real behavior in real-time.

The goal: **Quantify similarity** between predicted and actual behavior with percentage scores.

---

## Core Architecture: Shadow Mode

```
┌─────────────────────────────────────────────────────────────┐
│                    YOUR REAL INPUT                          │
│                  (mouse + keyboard)                         │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────┴───────────────────┐
        │                                       │
        ▼                                       ▼
┌───────────────────┐                 ┌───────────────────┐
│    COLLECTOR      │                 │    PREDICTOR      │
│                   │                 │                   │
│ Captures real     │                 │ Given start/end,  │
│ movement/typing   │                 │ ML model predicts │
│ Stores in RAM     │                 │ expected behavior │
└───────────────────┘                 └───────────────────┘
        │                                       │
        │         Real Data                     │    Predicted Data
        │                                       │
        └──────────────────┬────────────────────┘
                           │
                           ▼
                 ┌───────────────────┐
                 │    COMPARATOR     │
                 │                   │
                 │ Analyzes both     │
                 │ Calculates deltas │
                 └───────────────────┘
                           │
                           ▼
                 ┌───────────────────┐
                 │     SCORER        │
                 │                   │
                 │ Similarity %      │
                 │ Per-metric scores │
                 │ Overall grade     │
                 └───────────────────┘
                           │
                           ▼
                 ┌───────────────────┐
                 │    REPORTER       │
                 │                   │
                 │ Dashboard         │
                 │ Logs              │
                 │ Alerts            │
                 └───────────────────┘
```

---

## Workflow: Mouse Movement Validation

### Step 1: Trigger Detection
When a new movement starts:
- Capture start point (x, y)
- Wait for end event (click/scroll)
- Capture end point (x, y)

### Step 2: Parallel Processing

**Real Path (Collector):**
- Store all path points in RAM
- Calculate real metrics (speed, curvature, etc.)

**Predicted Path (Predictor):**
- Feed start/end to ML model
- Model generates predicted path
- Calculate predicted metrics

### Step 3: Comparison
Once movement ends:
- Compare real vs predicted
- Calculate similarity scores
- Log results

---

## Mouse Similarity Metrics

### 1. Path Shape Similarity

**Method: Fréchet Distance**

Measures how similar two curves are, considering the path ordering.

```
Fréchet distance = max distance between corresponding points
                   when traversing both paths optimally
```

**Scoring:**
| Fréchet Distance | Similarity Score |
|------------------|------------------|
| 0-10 px | 95-100% |
| 10-25 px | 85-95% |
| 25-50 px | 70-85% |
| 50-100 px | 50-70% |
| >100 px | <50% |

### 2. Speed Profile Similarity

Compare speed at normalized path positions (0%, 10%, 20%... 100%).

**Method: Correlation Coefficient**

```
r = correlation(real_speeds, predicted_speeds)
score = (r + 1) / 2 * 100%
```

| Correlation | Interpretation |
|-------------|----------------|
| 0.9 - 1.0 | Excellent match |
| 0.7 - 0.9 | Good match |
| 0.5 - 0.7 | Moderate match |
| < 0.5 | Poor match |

### 3. Duration Accuracy

```
duration_error = |real_duration - predicted_duration| / real_duration
score = max(0, 100 - duration_error * 100)
```

**Target:** Within 15% of real duration = good.

### 4. Curvature Match

```
real_curvature = real_path_length / real_distance
predicted_curvature = predicted_path_length / predicted_distance

curvature_error = |real - predicted| / real
score = max(0, 100 - curvature_error * 100)
```

### 5. Overshoot Detection Accuracy

| Real | Predicted | Score |
|------|-----------|-------|
| Has overshoot | Has overshoot | 100% |
| No overshoot | No overshoot | 100% |
| Has overshoot | No overshoot | 0% |
| No overshoot | Has overshoot | 0% |

If both have overshoot, also compare:
- Overshoot distance similarity
- Correction timing similarity

### 6. Pre-Click Pause Accuracy

```
pause_error = |real_pause - predicted_pause| / real_pause
score = max(0, 100 - pause_error * 100)
```

### 7. Endpoint Precision

How close is predicted endpoint to actual?

```
endpoint_error = distance(real_end, predicted_end)
score = max(0, 100 - endpoint_error * 2)  // -2% per pixel
```

---

## Keyboard Similarity Metrics

### 1. Digraph Timing Accuracy

For each key pair typed:

```
real_delay = actual delay between keys
predicted_delay = model's predicted delay

error = |real - predicted| / real
score = max(0, 100 - error * 100)
```

**Aggregate:** Average across all digraphs in session.

### 2. Key Hold Duration Accuracy

```
real_hold = actual key press duration
predicted_hold = model's predicted duration

error = |real - predicted| / real
score = max(0, 100 - error * 100)
```

### 3. Shortcut Execution Similarity

Compare full shortcut timing profile:

| Component | Weight |
|-----------|--------|
| Modifier pre-delay | 25% |
| Main key timing | 25% |
| Overlap duration | 25% |
| Release order/timing | 25% |

### 4. Burst Pattern Match

Detect bursts in both real and predicted, compare:
- Burst lengths
- Pause durations
- Within-burst speeds

**Method:** Dynamic Time Warping (DTW) on timing sequences.

### 5. Error Pattern Realism

If model injects errors:
- Are they at realistic positions?
- Is correction timing believable?
- Is error frequency similar to your real rate?

### 6. Overall Typing Rhythm

**Method:** Autocorrelation comparison

Your typing has a rhythm signature. Compare the autocorrelation function of real vs predicted inter-key intervals.

---

## Composite Scoring System

### Mouse Movement Score

| Metric | Weight |
|--------|--------|
| Path shape (Fréchet) | 30% |
| Speed profile | 20% |
| Duration | 15% |
| Curvature | 10% |
| Overshoot accuracy | 10% |
| Pre-click pause | 10% |
| Endpoint precision | 5% |

**Formula:**
```
mouse_score = Σ (metric_score × weight)
```

### Keyboard Input Score

| Metric | Weight |
|--------|--------|
| Digraph timing | 35% |
| Key hold duration | 20% |
| Shortcut execution | 15% |
| Burst patterns | 15% |
| Overall rhythm | 15% |

**Formula:**
```
keyboard_score = Σ (metric_score × weight)
```

### Overall Similarity Score

```
total_score = (mouse_score × 0.5) + (keyboard_score × 0.5)
```

Or weighted by actual usage ratio in session.

---

## Grading System

| Score | Grade | Interpretation |
|-------|-------|----------------|
| 95-100% | A+ | Indistinguishable from real |
| 90-95% | A | Excellent simulation |
| 85-90% | B+ | Very good, minor tells |
| 80-85% | B | Good, occasional anomalies |
| 70-80% | C | Acceptable, noticeable differences |
| 60-70% | D | Poor, clearly artificial |
| <60% | F | Failed, obviously bot-like |

**Target for production use: 85%+**

---

## Real-Time Dashboard

### Live Metrics Display

```
┌─────────────────────────────────────────────────────────────┐
│              SHADOW MODE - LIVE VALIDATION                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  SESSION: 2h 34m        MOVEMENTS: 1,847    KEYSTROKES: 12,453
│                                                             │
│  ┌─────────────────────┐    ┌─────────────────────┐        │
│  │   MOUSE SCORE       │    │   KEYBOARD SCORE    │        │
│  │                     │    │                     │        │
│  │      87.3%          │    │      91.2%          │        │
│  │       [B+]          │    │       [A]           │        │
│  └─────────────────────┘    └─────────────────────┘        │
│                                                             │
│  OVERALL: 89.2% [B+]                                       │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│                                                             │
│  MOUSE BREAKDOWN:              KEYBOARD BREAKDOWN:          │
│  • Path shape:    84%          • Digraph timing:  92%      │
│  • Speed profile: 89%          • Key hold:        88%      │
│  • Duration:      91%          • Shortcuts:       94%      │
│  • Curvature:     85%          • Burst pattern:   90%      │
│  • Overshoot:     82%          • Rhythm:          91%      │
│  • Pre-click:     88%                                      │
│  • Endpoint:      96%                                      │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│                                                             │
│  RECENT MOVEMENTS:                                          │
│  #1847  (234,156) → (891,423)  Score: 91%  ✓               │
│  #1846  (891,423) → (445,234)  Score: 78%  ⚠ path shape    │
│  #1845  (200,100) → (200,105)  Score: 94%  ✓               │
│                                                             │
│  PROBLEM AREAS:                                             │
│  ⚠ Long diagonal movements: avg 76%                        │
│  ⚠ Fast shortcuts (Ctrl+W): avg 71%                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Alerts

- **Yellow alert:** Score drops below 80% for 5+ consecutive actions
- **Red alert:** Score drops below 70% for any action
- **Pattern alert:** Specific movement/typing type consistently low

---

## Data Storage for Validation

### `validation_results` — Per-action scores

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Result ID |
| `session_id` | INTEGER FK | Validation session |
| `input_type` | TEXT | `mouse` or `keyboard` |
| `action_id` | INTEGER | Reference to movement/keystroke |
| `overall_score` | REAL | Combined score 0-100 |
| `metric_scores` | TEXT | JSON of individual metrics |
| `prediction_data` | TEXT | JSON of what model predicted |
| `timestamp` | DATETIME | When validated |

### `validation_sessions` — Session summaries

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Session ID |
| `started_at` | DATETIME | Session start |
| `ended_at` | DATETIME | Session end |
| `total_mouse_actions` | INTEGER | Movements validated |
| `total_keyboard_actions` | INTEGER | Keystrokes validated |
| `avg_mouse_score` | REAL | Average mouse score |
| `avg_keyboard_score` | REAL | Average keyboard score |
| `overall_score` | REAL | Combined average |
| `problem_areas` | TEXT | JSON of weak points |

### `validation_trends` — Long-term tracking

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Trend ID |
| `date` | DATE | Day |
| `model_version` | TEXT | Which model version |
| `avg_score` | REAL | Daily average |
| `mouse_score` | REAL | Mouse average |
| `keyboard_score` | REAL | Keyboard average |
| `actions_validated` | INTEGER | Total actions |

---

## Continuous Improvement Loop

```
┌─────────────────┐
│  Collect Data   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Train Model    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Shadow Test    │◄────────────────┐
└────────┬────────┘                 │
         │                          │
         ▼                          │
┌─────────────────┐                 │
│  Analyze Scores │                 │
└────────┬────────┘                 │
         │                          │
         ▼                          │
    Score > 90%?                    │
    ┌────┴────┐                     │
   Yes        No                    │
    │          │                    │
    ▼          ▼                    │
 Ready    Identify weak areas       │
 for      Add targeted training     │
 use      ─────────────────────────►┘
```

### Improvement Strategies

| Problem | Solution |
|---------|----------|
| Low path accuracy | More path point data, better interpolation |
| Speed profile off | More granular speed sampling |
| Overshoot missing | Explicit overshoot training data |
| Digraph timing off | Larger digraph sample size |
| Shortcuts wrong | Dedicated shortcut training set |

---

## Testing Modes

### 1. Live Shadow Mode
- Runs while you work
- Real-time comparison
- Dashboard display
- Continuous scoring

### 2. Batch Validation
- Take recorded session
- Run model predictions offline
- Detailed analysis report
- Good for model comparison

### 3. A/B Testing
- Compare two model versions
- Same real data, different predictions
- Statistical significance testing

### 4. Stress Testing
- Edge cases: very fast movements, long distances
- Unusual key combinations
- Fatigue conditions
- Find model limits

---

## Minimum Viable Validation

### Phase 1 — Basic Comparison
- [ ] Path Fréchet distance
- [ ] Duration comparison
- [ ] Simple percentage score
- [ ] Console logging

### Phase 2 — Full Mouse Metrics
- [ ] Speed profile correlation
- [ ] Curvature matching
- [ ] Overshoot detection
- [ ] Pre-click pause accuracy

### Phase 3 — Keyboard Metrics
- [ ] Digraph timing accuracy
- [ ] Key hold comparison
- [ ] Shortcut analysis

### Phase 4 — Dashboard & Reporting
- [ ] Real-time UI
- [ ] Historical trends
- [ ] Problem area identification
- [ ] Improvement recommendations

---

## Success Criteria

The model is **production-ready** when:

1. **Overall score ≥ 85%** sustained over 8+ hours
2. **No single metric below 70%**
3. **No pattern consistently below 80%**
4. **Score variance < 10%** (consistent performance)
5. **Edge cases score ≥ 75%**

At this point, the simulated input should be statistically indistinguishable from your real input to automated detection systems.
