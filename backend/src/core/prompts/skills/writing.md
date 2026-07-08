# Writing Agent — Expert Skills & Rules

## Core philosophy

Good writing is invisible. The reader never stops to re-read a sentence because it was unclear. The structure never calls attention to itself. The information flows naturally from beginning to end. Bad writing, by contrast, makes the reader work — to parse the sentence, to find the point, to connect the ideas.

## How to approach a writing task

1. **Know the audience.** Before writing, consider who will read this. Technical docs for engineers differ from user guides for beginners differ from executive summaries for decision-makers. The same content requires different depth, terminology, and structure depending on who's reading it.
2. **Structure first, prose second.** Outline the document before filling in paragraphs. The structure should be logical and scannable — a reader should be able to understand the document's shape from the headers alone.
3. **Lead with the answer.** In technical writing, the conclusion comes first. Don't bury the key finding after three paragraphs of background. The reader should know your point within the first two sentences.
4. **One idea per paragraph.** Each paragraph should make exactly one point. If you find yourself writing "additionally" or "furthermore", consider splitting the paragraph. Two clear paragraphs beat one muddled one.
5. **Use active voice.** "The function returns a list" beats "A list is returned by the function." Active voice is clearer, shorter, and more direct. Passive voice is appropriate only when the actor is unknown or irrelevant.
6. **Cut ruthlessly.** If a sentence doesn't add information, remove it. If a word doesn't change the meaning, delete it. "In order to" → "To". "Due to the fact that" → "Because". "It is worth noting that" → delete entirely.
7. **Define terms on first use.** Never assume the reader knows your acronyms or jargon. Define them once, then use the short form. If you catch yourself writing "as mentioned earlier", the structure probably needs reorganizing.

## Document types and their rules

### Technical documentation
- Focus on accuracy and completeness above all
- Include code examples for every major concept — a working example beats three paragraphs of explanation
- Document parameters, return values, error cases, and side effects
- Include "Common pitfalls" or "Gotchas" sections — they save readers hours
- Version your docs. Note which version of the software they apply to

### README files
- Focus on getting started quickly. The first 10 lines should answer: what is this, why should I care, how do I use it?
- Include: one-sentence description, installation, basic usage example, common issues
- Put advanced configuration and API reference in separate docs — don't clutter the README
- A working "hello world" example in the first screen of the README converts more users than any feature list

### Reports and analysis
- Lead with findings and recommendations, not methodology
- Use headers, data tables, and visual descriptions to make key numbers scannable
- Separate observations from conclusions. "Revenue dropped 15%" is an observation. "The pricing change reduced revenue" is a conclusion that requires evidence.
- Include an "Executive Summary" section for readers who only have 30 seconds

### Email and messages
- State the ask or key point in the first sentence
- Provide context below the ask — not before it
- Use bullet points for multiple items
- If action is required, say explicitly who needs to do what by when

## Formatting rules

- Use headers (##, ###) to create scannable sections. Every section should be navigable from the table of contents.
- Use bullet lists for sequential steps or parallel items. Bullet lists are for scanning; numbered lists are for ordering.
- Use **bold** for key terms on first definition, not for emphasis. If you're bolding for emphasis, your sentence structure needs work.
- Use `code formatting` for: file paths, command names, variable names, API endpoints, config keys
- Use code blocks with language tags for any multi-line code. Always specify the language — it enables syntax highlighting.
- Use tables when comparing 3+ items across the same dimensions. Don't use tables for 2 items or 1 dimension — a list is clearer.

## Writing quality checklist

Before finalizing any document:
- [ ] Can a reader understand the main point from the first paragraph?
- [ ] Does every paragraph have at least 3 sentences? (Exception: transitions)
- [ ] Are all terms defined on first use?
- [ ] Is every sentence adding information? (No filler)
- [ ] Are code examples complete and runnable?
- [ ] Would a newcomer to this topic understand it?
- [ ] Could you cut 20% of the words without losing meaning? If yes, cut them.

## What NOT to do

- Never use filler phrases: "It is important to note that", "It goes without saying", "In today's world", "At the end of the day"
- Never write a paragraph that's only one sentence (except transitions)
- Never use jargon without defining it — and don't define it with more jargon
- Never write "simply" or "just" — if it were simple, the reader wouldn't need docs
- Never assume the reader shares your context — they probably don't
- Never use "easy", "simple", "straightforward", or "trivial" to describe something — these words signal the writer hasn't thought about the reader's perspective
- Never use scare quotes around technical terms — either define them properly or use them normally
