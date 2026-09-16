# HPC Autograder for PrairieLearn (`scompgrader`)

`scompgrader` is a lightweight Python autograding helper designed for High-Performance Computing (HPC) and Supercomputing assignments running on [PrairieLearn](https://prairielearn.readthedocs.io/).

It provides automated grading for:
- **C++ compilation & static analysis** (OpenMP support, `-fanalyzer`, strict warning flags).
- **Runtime sanitizers** (AddressSanitizer, UndefinedBehaviorSanitizer, ThreadSanitizer).
- **I/O diff testing** (Standard input/output comparison with diff output).
- **Speedup & scalability benchmarking** (Comparing multi-threaded OpenMP execution against a baseline).
- **SLURM SBATCH validation** (Checking `#SBATCH` directives and required script commands).
- **PrairieLearn integration** (Automatic scoring and generation of `/grade/results/results.json`).

---

## Architecture Overview

The module consists of two main graders and several data transfer classes:

```
                      +-------------------+
                      |   grade(graders)  |
                      +---------+---------+
                                |
             +------------------+------------------+
             |                                     |
     +-------v-------+                     +-------v-------+
     |   CppGrader   |                     |  SbatchGrader |
     +-------+-------+                     +-------+-------+
             |                                     |
  +----------+----------+               +----------+----------+
  | - COMPILE           |               | - check_options()   |
  | - FANALYZE          |               | - check_commands()  |
  | - Sanitizers (ASan, |               +---------------------+
  |   UBSan, TSan)      |
  | - DiffTest (I/O)    |
  | - SpeedupTest       |
  +---------------------+
```

---

## Components

### Bitmask Flags for `CppGrader`

Flags can be combined using the bitwise OR (`|`) operator:

| Flag | Value | Description |
| :--- | :--- | :--- |
| `COMPILE` | `1 << 0` | Compiles using `g++ -fopenmp -Wall -Wextra -Wpedantic -Werror`. |
| `FANALYZE` | `1 << 2` | Runs GCC static analysis (`-fanalyzer`). |
| `ADDRESSAN` | `1 << 3` | Compiles & runs with AddressSanitizer (`-fsanitize=address`). |
| `UNDEFINEDSAN` | `1 << 4` | Compiles & runs with UndefinedBehaviorSanitizer (`-fsanitize=undefined`). |
| `THREADSSAN` | `1 << 5` | Compiles & runs with ThreadSanitizer (`-fsanitize=threads`). |
| `SPEEDUP` | `1 << 6` | Runs performance evaluation against a baseline runtime. |

---

### Data Classes

#### `DiffTest`
Defines an input/output test case for C++ binaries:
```python
@dataclass
class DiffTest:
    name: str   # Test name / label
    inpt: str   # Input fed into stdin
    outp: str   # Expected stdout output
```

#### `SpeedupTest`
Defines speedup criteria:
```python
@dataclass
class SpeedupTest:
    base_time: float      # Baseline sequential or reference execution time (seconds)
    min_speedup: float    # Minimum required speedup ratio (base_time / parallel_time)
    threads: int = 4      # OMP_NUM_THREADS to set during the test
    timeout: int = 120    # Timeout in seconds
```

#### `SbatchTest`
Specifies an expected `#SBATCH` directive:
```python
@dataclass
class SbatchTest:
    name: str     # Test description
    option: str   # Directive name (e.g., "--nodes", "--time", "-p")
    value: str    # Expected value (e.g., "1", "00:10:00", "compute")
```

#### `PLTest` & `PLResult`
Internal dataclasses used to format results into the PrairieLearn schema (`gradable`, `score`, and list of `tests` with points and feedback output).

---

## Grader Classes

### `CppGrader`
```python
CppGrader(filename, flags=COMPILE, tests=None, speedup=None)
```
- **`filename`**: Path to the student's C++ source file (e.g. `/grade/student/main.cpp`).
- **`flags`**: Combination of bitmask flags (e.g. `COMPILE | ADDRESSAN | SPEEDUP`).
- **`tests`**: List of `DiffTest` instances. Recompiles a clean non-sanitized binary before executing input/output tests.
- **`speedup`**: `SpeedupTest` instance. Recompiles without sanitizers, sets `OMP_NUM_THREADS`, measures execution time, and verifies the speedup target is met.
- **`run()`**: Executes all specified checks and returns a list of test results.

### `SbatchGrader`
```python
SbatchGrader(filename, options_tests=None, commands_tests=None)
```
- **`filename`**: Path to the submission batch script (e.g. `/grade/student/job.sh`).
- **`options_tests`**: List of `SbatchTest` instances checking for required `#SBATCH` directives and values.
- **`commands_tests`**: List of string substrings expected to be executed as shell commands in the script (excluding comments).
- **`run()`**: Parses the script and returns the verification results.

---

### Results Export

#### `grade(graders: list)`
Executes each grader in `graders`, aggregates total points earned vs. maximum points available, calculates a normalized score between `0.0` and `1.0`, and outputs results to `/grade/results/results.json`.

---

## Usage Example

Create a grading script (e.g., `grade.py`) in your PrairieLearn question autograder:

```python
from scompgrader import (
    CppGrader,
    SbatchGrader,
    DiffTest,
    SpeedupTest,
    SbatchTest,
    grade,
    COMPILE,
    FANALYZE,
    ADDRESSAN,
    UNDEFINEDSAN,
    THREADSSAN,
    SPEEDUP,
)

# 1. Configure C++ Tests
cpp_tests = [
    DiffTest(name="Small matrix test", inpt="4\n", outp="Result: 42\n"),
    DiffTest(name="Large matrix test", inpt="1024\n", outp="Result: 1048576\n"),
]

# 2. Configure Speedup Test (e.g. 4 threads should be at least 2.5x faster than 5.0s baseline)
speedup = SpeedupTest(base_time=5.0, min_speedup=2.5, threads=4, timeout=60)

cpp_grader = CppGrader(
    filename="/grade/student/solution.cpp",
    flags=COMPILE | FANALYZE | ADDRESSAN | UNDEFINEDSAN | THREADSSAN | SPEEDUP,
    tests=cpp_tests,
    speedup=speedup,
)

# 3. Configure SBATCH Script Checks
sbatch_tests = [
    SbatchTest(name="Partition check", option="--partition", value="parallel"),
    SbatchTest(name="Thread count", option="--cpus-per-task", value="4"),
]
commands = [
    "export OMP_NUM_THREADS=4",
    "./solution",
]

sbatch_grader = SbatchGrader(
    filename="/grade/student/job.sh",
    options_tests=sbatch_tests,
    commands_tests=commands,
)

# 4. Run Grading
grade([cpp_grader, sbatch_grader])
```

---

## Requirements & Environment

When configuring the PrairieLearn Docker container image for this autograder:
- **`g++` / `g++-14`**: Modern GCC compiler supporting `-fopenmp`, `-fanalyzer`, and runtime sanitizers (`-fsanitize=address,undefined,threads`).
- **Python 3.10+**: Standard library only (`dataclasses`, `subprocess`, `difflib`, `json`, `re`, `time`).
- **PrairieLearn Directory Layout**:
  - `/grade/student/`: Directory containing student submissions.
  - `/grade/results/results.json`: Output path generated automatically by `write_results`.
