# Transcript Batches for Judge Evaluation Experiments

This folder (`transcripts/batches/`) contains 198 batch files organized into three experimental types for comparative transcript analysis using the LLM judge system.

## Overview

The batch system enables **holistic grading experiments** where multiple transcripts are judged together, allowing the LLM to make comparative assessments rather than evaluating transcripts in isolation.

## Folder Structure

```
batches/
├── batches_raw/           # Source batch files (input)
│   ├── batch_01/          # Type 01: 72 batches (batch_001.txt - batch_072.txt)
│   ├── batch_02/          # Type 02: 54 batches (batch_001.txt - batch_054.txt)
│   └── batch_03/          # Type 03: 72 batches (batch_001.txt - batch_072.txt)
├── batches_gpt/           # GPT-graded batch output (JSON)
│   ├── batch_01/
│   ├── batch_02/
│   └── batch_03/
├── batches_claude/        # Claude-graded batch output (JSON)
│   ├── batch_01/
│   ├── batch_02/
│   └── batch_03/
├── batch_01.md            # Type 01 detailed explanation
├── batch_02.md            # Type 02 detailed explanation
├── batch_03.md            # Type 03 detailed explanation
└── README.md
```

## Batch Types

| Type | Description | Count | Path |
|------|-------------|-------|------|
| **01** | Same persona + version + exercise | 72 | `batch_01/batch_001.txt` – `batch_01/batch_072.txt` |
| **02** | Same persona + version, different exercise | 54 | `batch_02/batch_001.txt` – `batch_02/batch_054.txt` |
| **03** | Different persona, same version + exercise | 72 | `batch_03/batch_001.txt` – `batch_03/batch_072.txt` |

**Total**: 198 batch files covering 594 unique transcripts (3 per batch)

## Experimental Design Principles

### Zero Overlap Guarantee
- Each transcript appears in **exactly one batch** within each batch type
- No transcript is duplicated across batches of the same type
- This ensures clean statistical analysis without data contamination

### Controlled Variables
- **Type 01**: Controls persona, version, and exercise (tests judge consistency)
- **Type 02**: Controls persona and version (tests cross-exercise performance)
- **Type 03**: Controls version and exercise (tests persona differentiation)

### Systematic Coverage
- All available raw transcripts from `transcripts/{persona}/{persona}_raw/` are included
- Balanced representation across personas: `chaotic`, `chitchat`, `clueless`
- Covers both `philosophy` and `urban_studies` courses

## File Format

Each batch file contains 3 transcript paths (one per line):

```
# Batch Type X - Batch Y
# Generated batch with 3 transcripts

chaotic\chaotic_raw\transcript_01
chitchat\chitchat_raw\transcript_05
clueless\clueless_raw\transcript_12
```

## Usage

### Batch Experiment Runners (Recommended)

```bash
# 1. Edit BATCH_TYPE (1, 2, or 3) in the file
# 2. Run the experiment:
python run_batch_gpt.py     # GPT experiments
python run_batch_claude.py  # Claude experiments
```

**Batch Types:**
- `BATCH_TYPE = 1`: Consistency experiment (72 batches)
- `BATCH_TYPE = 2`: Cross-exercise experiment (54 batches)
- `BATCH_TYPE = 3`: Persona differentiation experiment (72 batches)

### Single Batch Judging
```python
from judge.run_judge_batch_gpt import judge_transcript_batch

results = judge_transcript_batch(
    "unused",
    batch_file_path="transcripts/batches/batch_01/batch_001.txt",
    output_name="experiment_consistency"
)
```

### Manual Batch Type Analysis
```python
for i in range(1, 73):  # 72 batches
    batch_file = f"transcripts/batches/batch_01/batch_{i:03d}.txt"
    results = judge_transcript_batch("unused", batch_file_path=batch_file)
```

## Research Questions

### Judge Reliability (Type 01)
- How consistent are scores for similar conversations?
- What's the acceptable variance threshold for judge reliability?
- Which rubric criteria show the most/least consistency?

### Cross-Exercise Validity (Type 02)
- Are some exercises systematically harder than others?
- Do student personas maintain consistent behavior across exercises?
- How should exercise difficulty be calibrated?

### Persona Differentiation (Type 03)
- Can the judge distinguish between different student types?
- Are scoring standards appropriately adapted for different learners?
- Which personas are most/least challenging to evaluate fairly?

## Output Analysis

### Individual Batch Results
Each judged batch produces 3 graded transcript files:
- `{output_name}_batch_01__{prompt}__{rubric}__gpt.json`
- `{output_name}_batch_02__{prompt}__{rubric}__gpt.json`
- `{output_name}_batch_03__{prompt}__{rubric}__gpt.json`

### Comparative Metrics
- **Score Variance**: Standard deviation within batches (Type 01)
- **Exercise Effects**: Mean score differences across exercises (Type 02)
- **Persona Profiles**: Characteristic score patterns by student type (Type 03)

## Generation

Batches were generated using an automated script that:
1. Discovered all raw transcripts in `transcripts/{persona}/{persona}_raw/`
2. Extracted metadata (persona, version, course, exercise)
3. Grouped transcripts according to batch type rules
4. Wrote batch files with zero overlap guarantee
5. Created documentation for each batch type

The 198 batch files are pre-generated and ready for use.

## Documentation

- **[batch_01.md](batch_01.md)**: Type 01 detailed explanation
- **[batch_02.md](batch_02.md)**: Type 02 detailed explanation
- **[batch_03.md](batch_03.md)**: Type 03 detailed explanation

## Next Steps

1. **Run Experiments**: Execute batch judging across all 198 batches
2. **Statistical Analysis**: Compute variance, correlation, and effect size metrics
3. **Judge Calibration**: Use results to refine judge prompts and rubrics
4. **Persona Validation**: Confirm student archetypes produce expected patterns
5. **Exercise Balancing**: Adjust exercise difficulty based on cross-exercise results
