# ML Model Architecture for Human Input Simulation

## Overview

This document defines the machine learning architecture for generating personalized human-like mouse movements and keyboard inputs based on recorded behavioral data.

The system consists of multiple specialized models working together, each handling a specific aspect of input simulation.

---

## Model Strategy: Ensemble Approach

Rather than one monolithic model, we use **specialized models** for different tasks:

```
┌─────────────────────────────────────────────────────────────┐
│                    INPUT SIMULATION SYSTEM                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  MOUSE MODELS                    KEYBOARD MODELS            │
│  ─────────────                   ───────────────            │
│  ├─ Path Generator               ├─ Digraph Timing          │
│  ├─ Speed Profile                ├─ Key Hold Duration       │
│  ├─ Overshoot Predictor          ├─ Shortcut Executor       │
│  ├─ Pre-Click Behavior           ├─ Burst Rhythm            │
│  └─ Micro-Jitter                 └─ Error Injector          │
│                                                             │
│  CONTEXT MODELS                                             │
│  ──────────────                                             │
│  ├─ Fatigue Modifier                                        │
│  ├─ Time-of-Day Adjuster                                    │
│  └─ Sequence Predictor                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Mouse Models

### 1. Path Generator Model

**Purpose:** Generate the (x, y) coordinates of the mouse path from start to end.

**Architecture:** Variational Autoencoder (VAE) or LSTM

**Input Features:**
| Feature | Type | Description |
|---------|------|-------------|
| `start_x`, `start_y` | int | Starting position |
| `end_x`, `end_y` | int | Target position |
| `distance` | float | Euclidean distance |
| `angle` | float | Direction angle (radians) |
| `quadrant` | int | Screen quadrant (1-4) |

**Output:**
- Sequence of normalized path points: `[(t, x, y), ...]`
- `t` = normalized time (0.0 to 1.0)
- `x, y` = normalized coordinates relative to start/end

**Training Data:**
- All recorded movements from `movements` + `path_points` tables
- Normalize paths to unit vector (start→end = 0→1)
- Store curvature patterns, not absolute coordinates

**Model Options:**

**Option A: VAE (Variational Autoencoder)**
```
Encoder: Path points → Latent space (32-64 dims)
Decoder: Latent + (start, end, distance, angle) → Path points

Advantage: Can sample variations from latent space
```

**Option B: LSTM/GRU Sequence Model**
```
Input: (start, end, distance, angle, step_number)
Output: (dx, dy) for each step

Advantage: Natural sequence generation
```

**Option C: KNN + Interpolation (Simpler)**
```
1. Find K nearest recorded movements (by distance, angle)
2. Select one randomly (weighted by similarity)
3. Scale and rotate to fit new start/end

Advantage: Always realistic (uses real data)
Disadvantage: Limited variation
```

**Recommendation:** Start with **Option C (KNN)** for MVP, upgrade to **VAE** for production.

---

### 2. Speed Profile Model

**Purpose:** Determine velocity at each point along the path.

**Architecture:** Neural Network or Statistical Model

**Input Features:**
| Feature | Type | Description |
|---------|------|-------------|
| `total_distance` | float | Path length |
| `path_position` | float | 0.0 to 1.0 (where on path) |
| `direction_angle` | float | Movement direction |
| `curvature_ahead` | float | How curved is upcoming path |

**Output:**
- `speed` at this path position (px/ms)

**Training Data:**
- Speed values from `path_points.speed` column
- Normalized by path position

**Key Patterns to Learn:**
- Acceleration phase (start slow)
- Cruise phase (middle, fastest)
- Deceleration phase (end slow)
- Your personal speed curve shape

**Simple Statistical Approach:**
```python
# Build speed profile percentiles from your data
speed_profile = {
    0.0: (min=0, p25=0.1, median=0.2, p75=0.3, max=0.5),
    0.1: (min=0.3, p25=0.5, median=0.8, p75=1.0, max=1.5),
    ...
    1.0: (min=0, p25=0.1, median=0.15, p75=0.2, max=0.3)
}

# Sample from distribution at each position
```

---

### 3. Overshoot Predictor

**Purpose:** Decide if this movement should overshoot, and by how much.

**Architecture:** Classification + Regression

**Input Features:**
| Feature | Type | Description |
|---------|------|-------------|
| `distance` | float | Movement distance |
| `speed` | float | Average movement speed |
| `angle` | float | Direction |
| `target_size` | float | If known (optional) |

**Output:**
- `has_overshoot`: boolean (will this movement overshoot?)
- `overshoot_distance`: float (how many pixels past target)
- `correction_time`: float (ms to correct back)

**Training Data:**
- `movements.has_overshoot`, `movements.overshoot_distance`
- Correlation with speed, distance, angle

**Model:** Simple logistic regression for classification, linear regression for distance.

---

### 4. Pre-Click Behavior Model

**Purpose:** Generate the hover behavior before clicking.

**Output:**
- `pause_duration`: How long to wait before clicking
- `jitter_pattern`: Micro-movements during pause

**Training Data:**
- `movements.pre_click_pause_ms`
- `movements.pre_click_jitter_px`

**Approach:**
```python
# Sample from your recorded distributions
pause = sample_from_distribution(pre_click_pauses)
jitter = generate_perlin_noise(amplitude=your_avg_jitter)
```

---

### 5. Micro-Jitter Generator

**Purpose:** Add realistic hand tremor during hover/pause states.

**Not ML — Procedural Generation:**

```python
def generate_jitter(duration_ms, amplitude_px):
    """Generate Perlin noise-based jitter pattern."""
    points = []
    t = 0
    while t < duration_ms:
        dx = perlin_noise(t * 0.01) * amplitude_px
        dy = perlin_noise(t * 0.01 + 1000) * amplitude_px
        points.append((t, dx, dy))
        t += 8  # ~125Hz
    return points
```

**Parameters from your data:**
- `amplitude`: stddev of your hover positions
- `frequency`: your jitter frequency characteristics

---

## Keyboard Models

### 1. Digraph Timing Model

**Purpose:** Predict delay between any two consecutive keys.

**Architecture:** Lookup Table + Neural Network Fallback

**Primary Approach: Lookup Table**
```python
# Built from digraph_stats table
digraph_timings = {
    ('t', 'h'): Distribution(mean=45, std=12),
    ('q', 'z'): Distribution(mean=180, std=35),
    ...
}

def get_delay(key1, key2, mode='text'):
    if (key1, key2) in digraph_timings[mode]:
        return digraph_timings[mode][(key1, key2)].sample()
    else:
        return fallback_model.predict(key1, key2, mode)
```

**Fallback Neural Network:**
For unseen key pairs, predict based on:
- Physical key distance
- Same hand / different hand
- Same finger / different finger

**Input Features:**
| Feature | Type | Description |
|---------|------|-------------|
| `key1_row` | int | Keyboard row (0-4) |
| `key1_col` | int | Keyboard column (0-14) |
| `key2_row` | int | Target key row |
| `key2_col` | int | Target key column |
| `same_hand` | bool | Both keys same hand? |
| `same_finger` | bool | Both keys same finger? |
| `typing_mode` | enum | text/code/shortcut/etc |

**Output:**
- `delay_ms`: Predicted inter-key delay

---

### 2. Key Hold Duration Model

**Purpose:** How long to hold each key down.

**Architecture:** Per-key distribution lookup

```python
# From key_hold_stats table
key_holds = {
    'a': Distribution(mean=85, std=15),
    'space': Distribution(mean=95, std=20),
    'shift': Distribution(mean=250, std=80),  # Modifiers held longer
    ...
}

def get_hold_duration(key, mode='text'):
    return key_holds[key].sample()
```

---

### 3. Shortcut Executor Model

**Purpose:** Execute keyboard shortcuts with your timing signature.

**Architecture:** Template-based with learned parameters

**Stored Templates:**
```python
shortcuts = {
    'ctrl+c': {
        'modifier_pre_delay': Distribution(mean=15, std=8),
        'main_key_delay': Distribution(mean=45, std=12),
        'overlap_duration': Distribution(mean=60, std=20),
        'release_order': 'main_first',  # or 'modifier_first'
        'modifier_release_delay': Distribution(mean=25, std=10)
    },
    'ctrl+shift+esc': {
        ...
    }
}
```

**Execution:**
```python
async def execute_shortcut(shortcut_name):
    template = shortcuts[shortcut_name]

    # Press modifiers
    for mod in template.modifiers:
        await press_key(mod)
        await sleep(template.modifier_pre_delay.sample())

    # Press main key
    await press_key(template.main_key)
    await sleep(template.overlap_duration.sample())

    # Release in learned order
    if template.release_order == 'main_first':
        await release_key(template.main_key)
        await sleep(template.modifier_release_delay.sample())
        for mod in reversed(template.modifiers):
            await release_key(mod)
    else:
        ...
```

---

### 4. Burst Rhythm Model

**Purpose:** Replicate your typing rhythm (bursts and pauses).

**Architecture:** Hidden Markov Model (HMM) or simple state machine

**States:**
- `BURST`: Fast typing (short inter-key delays)
- `PAUSE`: Thinking/reading (longer gaps)

**Learned Parameters:**
- Average burst length (characters)
- Average pause duration
- Transition probabilities

```python
class TypingRhythm:
    def __init__(self, your_stats):
        self.avg_burst_length = your_stats.avg_burst_length
        self.burst_delay_range = your_stats.burst_delays
        self.pause_duration_range = your_stats.pause_durations

    def get_delay_for_position(self, chars_in_current_burst):
        if chars_in_current_burst >= self.should_pause():
            return self.pause_duration_range.sample()  # Long pause
        else:
            return self.burst_delay_range.sample()  # Short delay
```

---

### 5. Error Injector (Optional)

**Purpose:** Occasionally make realistic typos and corrections.

**Your Error Profile:**
- Error rate: X per 100 characters
- Common error types (adjacent key, transposition, etc.)
- Correction speed

**Implementation:**
```python
def maybe_inject_error(intended_key, error_rate):
    if random.random() < error_rate:
        # Type wrong key
        wrong_key = get_adjacent_key(intended_key)
        yield wrong_key

        # Pause (noticing error)
        yield ('pause', your_error_notice_delay.sample())

        # Backspace
        yield 'backspace'

        # Correct key
        yield intended_key
    else:
        yield intended_key
```

---

## Context Models

### 1. Fatigue Modifier

**Purpose:** Adjust all timings based on how long the session has been running.

**Input:** `session_duration_minutes`

**Output:** Multipliers for:
- Movement speed (decreases)
- Click precision (decreases)
- Typing speed (decreases)
- Error rate (increases)

**Simple Linear Model:**
```python
def fatigue_multiplier(session_minutes):
    # Speed decreases ~5% per hour
    speed_mult = 1.0 - (session_minutes / 60) * 0.05

    # Errors increase ~10% per hour
    error_mult = 1.0 + (session_minutes / 60) * 0.10

    return {
        'speed': max(0.7, speed_mult),
        'precision': max(0.8, speed_mult),
        'error_rate': min(2.0, error_mult)
    }
```

---

### 2. Time-of-Day Adjuster

**Purpose:** Account for morning vs evening behavioral differences.

**Training Data:**
- Aggregate stats by `hour_of_day` from recordings

**Output:** Similar multipliers as fatigue model

---

## Training Pipeline

### Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   SQLite    │────►│  Processor  │────►│  Training   │
│  Database   │     │  & Feature  │     │   Script    │
│             │     │  Extraction │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │   Trained   │
                                        │   Models    │
                                        │  (.pkl/.pt) │
                                        └─────────────┘
```

### Training Script Structure

```python
# train_models.py

def train_path_generator():
    """Train VAE/LSTM for path generation."""
    paths = load_normalized_paths()
    model = PathVAE()
    model.fit(paths)
    model.save('models/path_generator.pt')

def build_digraph_table():
    """Build lookup table from digraph_stats."""
    stats = load_digraph_stats()
    table = {}
    for row in stats:
        key = (row.from_key, row.to_key, row.typing_mode)
        table[key] = Distribution(row.avg_delay, row.stddev)
    save_pickle(table, 'models/digraph_table.pkl')

def train_all():
    train_path_generator()
    train_speed_profile()
    train_overshoot_predictor()
    build_digraph_table()
    build_key_hold_table()
    build_shortcut_templates()
    ...
```

### Minimum Training Data

| Model | Minimum Samples | Recommended |
|-------|-----------------|-------------|
| Path Generator | 1,000 movements | 10,000+ |
| Speed Profile | 500 movements | 5,000+ |
| Overshoot | 200 with overshoot | 1,000+ |
| Digraph Timing | 50 per common pair | 500+ per pair |
| Key Hold | 100 per key | 500+ per key |
| Shortcuts | 20 per shortcut | 100+ per shortcut |

**Estimated recording time:** 20-40 hours of normal computer use.

---

## Model Files Structure

```
models/
├── mouse/
│   ├── path_generator.pt        # VAE/LSTM model
│   ├── speed_profile.pkl        # Speed distributions
│   ├── overshoot_model.pkl      # Logistic + linear
│   ├── pre_click_stats.pkl      # Pause distributions
│   └── jitter_params.json       # Amplitude, frequency
├── keyboard/
│   ├── digraph_table.pkl        # Key pair timings
│   ├── key_holds.pkl            # Per-key durations
│   ├── shortcuts.pkl            # Shortcut templates
│   ├── burst_params.json        # Rhythm parameters
│   └── error_profile.json       # Error injection params
├── context/
│   ├── fatigue_model.pkl        # Fatigue adjustments
│   └── time_of_day.pkl          # Hourly adjustments
└── metadata.json                # Version, training date, stats
```

---

## Inference API

```python
class HumanSimulator:
    """Main interface for generating human-like input."""

    def __init__(self, models_path='models/'):
        self.path_gen = load_model('mouse/path_generator.pt')
        self.speed_profile = load_pickle('mouse/speed_profile.pkl')
        self.digraphs = load_pickle('keyboard/digraph_table.pkl')
        # ... load all models

    def generate_mouse_movement(self, start, end) -> List[PathPoint]:
        """Generate complete mouse movement with timing."""
        # 1. Generate base path
        path = self.path_gen.generate(start, end)

        # 2. Apply speed profile
        path = self.speed_profile.apply(path)

        # 3. Maybe add overshoot
        if self.overshoot_model.should_overshoot(start, end):
            path = self.add_overshoot(path)

        # 4. Apply fatigue modifier
        path = self.fatigue.adjust(path)

        return path

    def generate_click(self) -> ClickParams:
        """Generate click timing parameters."""
        return ClickParams(
            pre_pause=self.pre_click.sample(),
            hold_duration=self.click_hold.sample(),
            post_pause=self.post_click.sample(),
            recoil=self.recoil.sample()
        )

    def generate_typing(self, text, mode='text') -> List[KeyEvent]:
        """Generate key events for typing text."""
        events = []
        prev_key = None

        for char in text:
            # Get timing
            if prev_key:
                delay = self.digraphs.get_delay(prev_key, char, mode)
                events.append(WaitEvent(delay))

            # Get hold duration
            hold = self.key_holds.get_duration(char, mode)

            events.append(KeyDown(char))
            events.append(WaitEvent(hold))
            events.append(KeyUp(char))

            prev_key = char

        return events

    def generate_shortcut(self, shortcut_name) -> List[KeyEvent]:
        """Generate events for keyboard shortcut."""
        return self.shortcuts.execute(shortcut_name)
```

---

## MVP Implementation Order

### Phase 1: Statistical Models (No ML)
- [x] Define architecture
- [ ] KNN path lookup (from real recordings)
- [ ] Speed profile from percentiles
- [ ] Digraph lookup table
- [ ] Key hold lookup table

### Phase 2: Simple ML Models
- [ ] Overshoot classifier (logistic regression)
- [ ] Fallback digraph predictor (small NN)
- [ ] Fatigue linear model

### Phase 3: Advanced Models
- [ ] Path Generator VAE
- [ ] Burst rhythm HMM
- [ ] Error injection model

### Phase 4: Integration
- [ ] HumanSimulator API
- [ ] Robin integration
- [ ] Shadow mode validation

---

## Polling Rate Model

### Purpose
Match your mouse's actual polling rate during replay.

### Why This Matters
Websites can infer polling rate from timestamp gaps. Mismatched rates = detection risk.

### What We Record

During training phase, from `path_points` timestamps:

```python
def analyze_polling_rate(movements):
    all_intervals = []
    
    for movement in movements:
        points = movement.path_points
        for i in range(1, len(points)):
            interval = points[i].timestamp_ms - points[i-1].timestamp_ms
            all_intervals.append(interval)
    
    return {
        'avg_interval_ms': np.mean(all_intervals),      # e.g., 8.0
        'stddev_ms': np.std(all_intervals),             # e.g., 0.4
        'polling_rate_hz': 1000 / np.mean(all_intervals),  # e.g., 125
        'interval_distribution': all_intervals          # Full data for sampling
    }
```

### Replay Usage

```python
class PollingRateModel:
    def __init__(self, recorded_stats):
        self.avg_interval = recorded_stats['avg_interval_ms']
        self.stddev = recorded_stats['stddev_ms']
        self.distribution = recorded_stats['interval_distribution']
    
    def get_next_interval(self):
        # Option A: Gaussian sampling
        return max(1, random.gauss(self.avg_interval, self.stddev))
        
        # Option B: Direct sampling from recorded data (more realistic)
        # return random.choice(self.distribution)
```

### Expected Results by Mouse Type

| Your Mouse | Detected Rate | Avg Interval | StdDev |
|------------|---------------|--------------|--------|
| Basic USB | ~125 Hz | ~8.0ms | ~0.3-0.5ms |
| Budget gaming | ~250 Hz | ~4.0ms | ~0.2-0.4ms |
| Gaming | ~500 Hz | ~2.0ms | ~0.1-0.3ms |
| Pro gaming | ~1000 Hz | ~1.0ms | ~0.1-0.2ms |

---

## Notes

- Start simple (statistical/KNN), upgrade to ML only where needed
- Real recorded data is always more realistic than generated
- Keep models small — inference must be fast (< 5ms per movement)
- Retrain periodically as more data is collected
- Version models and track performance over time
