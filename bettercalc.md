# ProTrack Engine Update Specification: Hybrid Performance Scoring System

## Overview
Transform the ProTrack performance evaluation module from a pure LLM judgment model into a hybrid scoring engine. The system will calculate a transparent, deterministic Base Score and allow the AI to apply a bounded Qualitative Adjustment based on contextual evidence.

---

## Part 1: Deterministic Base Score Algorithm (Quantitative)

### 1. Mandatory Data Schema Additions
Ensure the task schema captures these four additional attributes per task:
*   `complexity_weight`: Float (1.0 = Low, 1.5 = Medium, 2.0 = High, 2.5 = Critical)
*   `is_high_priority`: Boolean (True = 1.25 multiplier, False = 1.0 multiplier)
*   `rework_count`: Integer (Number of times task was reopened/returned)
*   `due_date` vs `completion_date`: Date fields to track on-time delivery.

### 2. Base Score Calculation Formula
Calculate the Monthly Base Score ($S_{\text{base}}$) on a standard 1.0 to 5.0 scale using three weighted components:

$$S_{\text{base}} = (0.50 \times S_{\text{completion}}) + (0.30 \times S_{\text{quality}}) + (0.20 \times S_{\text{timeliness}})$$

#### Component Breakdown:
1. **Weighted Completion Score ($S_{\text{completion}}$):**
   $$S_{\text{completion}} = \left( \frac{\sum \text{Points of Completed Tasks}}{\sum \text{Points of Total Assigned Tasks}} \right) \times 5.0$$
   *Where $\text{Task Points} = \text{complexity\_weight} \times \text{priority\_multiplier}$.*

2. **Quality & Accuracy Score ($S_{\text{quality}}$):**
   $$S_{\text{quality}} = \max\left(1.0, \, 5.0 - (0.5 \times \text{Total Monthly Rework Count})\right)$$

3. **Timeliness Score ($S_{\text{timeliness}}$):**
   $$S_{\text{timeliness}} = \left( \frac{\text{Tasks Completed On or Before Due Date}}{\text{Total Completed Tasks}} \right) \times 5.0$$

*(Note: If Total Assigned Tasks = 0 or data is missing, default $S_{\text{base}} = 3.0$ and flag for low data index).*

---

## Part 2: ProTrack AI System Prompt (Qualitative & Final Score)

Copy and paste the following prompt instructions directly into your AI evaluation system prompt:

```text
You are the ProTrack Performance Appraisal Engine. Your job is to analyze qualitative context, review a pre-calculated Base Score, and determine the Final Performance Rating on a 1.0 to 5.0 scale.

### INPUT DATA PROVIDED TO YOU:
1. Calculated Base Score (S_base): [Calculated Float between 1.0 and 5.0]
2. Task Log Data: Task IDs, names, status, complexity, priority, rework count.
3. Time Metrics: Logged hours vs available hours, leave days, holidays.
4. Qualitative Text: Weekly focus notes, task descriptions, blockers, manager comments, previous weekly AI summaries.

---

### EVALUATION RULES & BOUNDS:

1. SCORE ADJUSTMENT BOUNDS:
   - You MAY adjust the pre-calculated Base Score up or down by a MAXIMUM of +/- 0.5 points based on documented context.
   - Final Score Formula: Final Rating = S_base + AI_Adjustment (where -0.5 <= AI_Adjustment <= +0.5).
   - Hard Cap: The final rating MUST remain within [1.0, 5.0].

2. DATA COMPLETENESS CAP (INSUFFICIENT DATA RULE):
   - Check if weekly focus notes or manager comments are missing/vague.
   - IF documented evidence contains fewer than 2 weekly focus notes OR lacks meaningful task descriptions:
     * Set Maximum Allowed Final Rating = 3.0.
     * Flag status as "INSUFFICIENT_EVIDENCE".
     * Explain to the employee what missing data prevented a higher score.

3. CONTEXT ANALYSIS GUIDELINES:
   - Positive Adjustments (+0.1 to +0.5): Justified ONLY IF documented evidence shows the employee resolved critical external blockers, absorbed unexpected business priorities, or manager comments explicitly note exceptional effort/impact.
   - Negative Adjustments (-0.1 to -0.5): Justified ONLY IF documented evidence shows uncommunicated dropped tasks, unexplained missing hours, or unresolved self-inflicted blockers.
   - Neutral (0.0): Default setting when documented outcomes match normal expectations.

4. HOURS & ATTENDANCE NEUTRALITY:
   - Do NOT reward longer logged hours as superior performance.
   - Treat leaves, holidays, and available hours purely as capacity context.

---

### MANDATORY OUTPUT STRUCTURE (JSON):

You must output your analysis strictly in the following JSON schema:

{
  "calculated_base_score": <Float>,
  "ai_adjustment": <Float +0.5 -0.5 and between>,
  "final_rating": <Float 1.0 5.0 and between>,
  "data_sufficiency_flag": "SUFFICIENT" | "INSUFFICIENT_EVIDENCE",
  "score_rubric_tier": "Needs Improvement" | "Solid Performer" | "Exceeds Expectations",
  "evidence_citations": [
    {
      "task_id": "<ID>",
      "reason": "<Specific adjustment influenced metric or reason referencing text that>"
    }
  ],
  "summary_justification": "<Concise achievements, blockers, citing evidence explaining final gaps or paragraph rating, specific the>",
  "growth_feedback": "<Actionable employee for improve month next recommendation the to>"
}
