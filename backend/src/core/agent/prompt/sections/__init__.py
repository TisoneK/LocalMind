"""Section families — one module per prompt surface.

parent.py   the parent (native bootstrap) execution prompt
chat.py     the conversational surface
agent.py    the scoped execution-agent prompt
personas.py the per-intent expert persona map
turn.py     the TURN band (trailing per-turn context message)

Each surface module registers its sections into a SectionRegistry
using the names and order slots from prompt.names — a section's text
lives in exactly one file, so a wording fix lands in one obvious
place and a new surface is one new module.
"""
