# Dynamic Rubric Generation Specification & Normalization Algorithms

This document describes the specification and normalization procedures used by `JobHunterKit` to dynamically synthesize and evaluate custom scoring rubrics for target job descriptions.

## Overview

When evaluating a candidate's CV against a Job Description (JD), a static evaluation rubric might fail to capture unique roles, specific tech stacks, or soft skills. JobHunterKit uses a **Dynamic Rubric Synthesis** loop to generate a job-specific evaluation framework before scoring.

---

## 1. Dynamic Rubric Synthesis Spec

During Phase 2 of the pipeline, if the `--dynamic-rubric` option is enabled, `score_jd.py` queries the LLM with the job description text using a structured prompt. 

### Prompt Structure & Requirements
- **Categories (Pillars)**: Generates exactly 4 custom evaluation categories representing core dimensions of the role (e.g., technical skills, leadership, project delivery, cultural fit).
- **Criteria**: Each category must define exactly 2-3 specific criteria items with descriptions.
- **Constraints**: Weights must be assigned to both categories and criteria, summing to 100% at the root and matching the category weight at the branch.

### Output JSON Schema
The LLM must return a raw JSON structure matching this schema:

```json
{
  "version": "1.0",
  "description": "Short explanation of the rubric focus",
  "pass_threshold": 80,
  "categories": [
    {
      "id": "1",
      "name": "Product Design & Implementation Skills",
      "weight_percent": 30,
      "criteria": [
        {
          "id": "1.1",
          "name": "End-to-End Product Delivery",
          "weight_percent": 15,
          "description": "Shipping complete features using agentic tools..."
        }
      ]
    }
  ]
}
```

---

## 2. Weight Normalization Algorithm

Since LLM generation can produce minor rounding or summing errors, JobHunterKit executes a post-generation normalization sequence to guarantee mathematical consistency.

### Steps
1. **Normalize Category Weights**: Category weights are redistributed to sum exactly to 100%.
2. **Normalize Criteria Weights**: Within each category, criteria weights are redistributed to sum exactly to their parent category's normalized weight.

### Integer Redistribution Logic (`_redistribute_weights`)
The redistribution handles fractional values robustly using integer rounding and remainder allocation:

1. **Sum raw weights**: Sum up all raw item weights (`total_raw`).
2. **Distribution**:
   - **Case A: `total_raw > 0`**:
     For each item (except the last), calculate the normalized weight:
     $$\text{norm\_w} = \text{round}\left( \frac{\text{item.weight}}{\text{total\_raw}} \times \text{target\_total} \right)$$
     Keep a running sum of all assigned weights.
     The last item receives the remaining weight to ensure absolute summation:
     $$\text{last.weight} = \text{target\_total} - \text{running\_sum}$$
   - **Case B: `total_raw == 0`**:
     If all weights are zero, divide the target weight evenly:
     $$\text{even\_w} = \lfloor \text{target\_total} / N \rfloor$$
     The last item receives the remaining remainder.
