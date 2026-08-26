# Material-First Retrieval Protocol

Purpose: stop Rigel from answering course-specific questions from memory when course files exist.

## Trigger

Use this protocol before answering any question about:

- Course facts or concepts
- Schedule, readings, assignments, exams, due dates, or grading
- "What should I study next?" or priority decisions tied to a course
- Quiz/cram generation, grading, or study planning that depends on course materials

Do not use this protocol for general study strategy, meta-learning, or non-course-specific advice.

## Steps

1. Identify the course.
   - If ambiguous, ask one short clarification.
   - If obvious from channel/session/context, proceed.
2. Locate the course folder under `courses/[course-id]/`.
3. Inspect relevant files only. Prefer, in order:
   - Course control files (`cram-control-*.md`, `course-model.md`, `exam-objectives.md`)
   - Syllabus/schedule files
   - Scorecards and reference files
   - Uploaded notes, slides, readings, and extracted text
   - Semester context when the question is schedule/status related
4. Answer with a `Checked:` line naming the files used.
5. If files are missing, say so clearly before using general knowledge.

## Missing files behavior

If no course files exist for the course:

> I don't have course materials loaded for [course]. Until then, I'm answering from general knowledge.

Then answer only if a general answer is useful. If the answer depends on a syllabus, professor-specific scope, exam format, or uploaded material, ask Johnny to send the missing material.

## Answer discipline

- Do not cite a file you did not inspect.
- Do not say "based on course materials" unless the answer actually came from files.
- If course files disagree, state the conflict and prefer the newest source unless a syllabus/exam prompt is clearly authoritative.
- For cram/quiz work, always inspect the scorecard/reference/control files before generating questions.
