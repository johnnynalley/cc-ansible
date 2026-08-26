# Course State Templates

These templates are Phase 2 scaffolding for Rigel's adaptive learning system. They are not required for every old course immediately. Create them when a course becomes active or when Johnny starts repeated study sessions.

Recommended per-course files under `courses/[course-id]/`:

- `course-model.md` - concept map, units, dependencies, source anchors
- `source-index.json` - machine-readable list of syllabi, slides, readings, notes, scorecards, references
- `schedule.md` - exams, deadlines, readings, class meetings, and study windows
- `concept-mastery.json` - future authoritative state for mastery counts and prompt history
- `question-history.jsonl` - append-only history of asked questions and results
- `due-reviews.json` - spaced review queue
- `weak-areas.md` - human-readable weak areas and recurring confusions
- `exam-objectives.md` - exam-specific scope, likely formats, professor hints, and high-yield priorities

Phase 1 remains compatible with the existing scorecard/reference files. Do not delay a cram session just because these files are missing.
