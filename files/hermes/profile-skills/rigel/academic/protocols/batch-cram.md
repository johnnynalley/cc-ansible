# Batch Cram Protocol

Purpose: help Johnny cover the highest-yield material quickly without pretending same-session repetition equals mastery.

Cram posture: if Johnny is severely underprepared, do not assume cold recall should be strong. Use simple, direct, course-grounded questions, fast corrections, miss-pattern tracking, and spaced retesting. Avoid over-engineering study mechanics mid-cram when the basic loop works better: question → answer → correction → next question. In Discord/live chat, account for assistant latency: Johnny may prefer multiple questions per turn for efficiency; apply the packet-size rules below rather than forcing single-question turns.

## Startup

Before starting a cram packet, read:

1. The relevant `cram-control-*.md` file if it exists
2. The exam scorecard
3. The exam reference file
4. Any exam prompt/objectives/syllabus section needed for scope

If no cram-control file exists, create a short one before a long cram session when time allows. It should include exam details, required startup files, high-yield priorities, packet strategy, and pacing rules.

## Packet sizes

- Default: 5-7 open-recall questions
- Rescue: 3-5 questions when accuracy is below about 50%, Johnny is vague, or concepts are mixing together
- Exposure: 10 questions only for familiar review or fast breadth checks

## Packet composition

Early session, no performance data:

- Prefer high-yield untested concepts from the cram-control file or reference
- Mix document/source ID, lecture arcs, dates/anchors, and one synthesis/comparison question

After performance data exists:

- Prioritize `[!!]` and `[!]` concepts only after real spacing; do not hammer the same misses packet after packet
- If broad course coverage is still weak or Johnny is frustrated by repetition, switch to coverage-first salvage: rotate across major exam clusters before returning to prior misses
- Include `[~]` concepts needing second-form confirmation only after spacing/interference
- Add untested high-yield concepts until coverage is broad enough
- Include occasional synthesis questions to force connections

## Question rules

- Every question gets a concept tag before it is sent, but concept tags must not reveal the answer. If the prompt asks Johnny to identify a person/source/term, use a neutral tag like `[Source ID]`, `[Gendered slavery]`, `[Abolitionist publication]`, or a concept number without the answer name.
- Use open recall: identify/significance, cause/effect, definition + connection, chronology, comparison, historically grounded scenario
- No two-option questions
- No recognition-choice stems disguised as open recall (e.g., “writing, legal argument, rescue work, or proslavery ideology?”)
- No giveaway fill-in-the-blank stems
- No answer-bearing mini-spines or previews immediately before a question on the same concept; previews must be meta-level, not content clues
- Do not repeat the same visible question
- Do not ask the same concept back-to-back after a correction or answer unless Johnny explicitly requests drill/rehearsal. Just-corrected concepts must be spaced by at least one full intervening packet or several unrelated questions before retest. Immediate retests are regurgitation risk and cannot upgrade the concept to `[X]`.

## Grading and updates

After Johnny answers a packet:

1. Grade every answer individually: Correct / Partially Correct / Incorrect
2. Give brief corrections that include the original question or a compact restatement of it with the answer, so Johnny does not need to scroll back
3. Track both what Johnny missed and how he missed it. Use miss-pattern labels when useful: no recall/blank, wrong target, concept confusion, overgeneralized answer, wrong identity/source, missing mechanism, missing significance, chronology error, answer-leakage/regurgitation risk, or lucky/familiarity risk. Store recurring/important patterns in scorecard notes and weak-areas.
4. Update the scorecard before generating the next packet
5. Include learning progress near the top of the reply every time: packet result, mastery count/percentage, confirmed-once count, active weak areas, any mode change, and brief learning insights when useful (miss patterns, confusion clusters, improving areas, pacing/fatigue signals, and why the next packet is shaped the way it is). Keep insights meta-level; do not give answer-bearing previews immediately before asking about the same concepts.
6. Recycle misses only after real spacing/interference; do not keep returning to the same few concepts when Johnny needs broad course exposure. If recycling is causing frustration or fake short-term recall, delay it and rotate to new clusters.
7. Mark immediate same-concept retests as regurgitation-risk repair/rehearsal or cram confidence, not durable mastery
8. Do not teach a survival skeleton and immediately quiz the same skeleton as if it measures recall. After teaching, use encode-delay-retrieve: cold blurt baseline → short correction/encoding hook → unrelated interference → delayed cold retrieval/application.

## Essay and short-answer prompts

For complex outlines or short-answer prompts, do not over-trust auto-grading. Show expected key points and ask Johnny which ones he missed when useful. Use this to train self-assessment and prioritize the next packet.

## Time collapse rule

If time is almost gone, stop chasing 100% coverage. Focus on:

1. High-yield misses
2. Source/document identification
3. Big comparison prompts
4. Dates/numbers only where they anchor major arguments
5. One final synthesis pass
