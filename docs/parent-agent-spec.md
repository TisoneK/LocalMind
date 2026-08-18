<!--
  PROVENANCE — This is a user-authored specification, captured verbatim into the
  repo on 2026-08-18 (Session 297) as the canonical statement of LocalMind's
  Parent Agent target architecture. The text below §"Reconciliation" is the
  author's document, unmodified. Do not edit the spec body to match code; if the
  code diverges, record the divergence in the Reconciliation section and in
  plans/decisions.md — the spec is the intended destination, not a description of
  the current build.
-->

# Parent Agent — Complete Functional Architecture & Development Specification

> **Status in LocalMind:** north-star architecture for the current development
> phase. See the Reconciliation note directly below before reading the spec —
> the shipped codebase has already run *ahead* of this spec in one important way.

---

## Reconciliation with the current LocalMind build (2026-08-18, Session 297)

This spec defines a **single-agent-first** program: the Parent Agent is the
entire autonomous intelligence layer for now, and **specialist agents,
delegation, and multi-agent orchestration are explicitly out of scope** (spec
§1, §9, §36). The goal of the phase is a *strong single-agent runtime* that can
later become the foundation for a multi-agent system.

Two facts about the current repo matter when reading this:

1. **The closed loop already exists and is actively hardened.** The lifecycle
   this spec describes — understand → diagnose → plan → act → observe → assess →
   recover → verify → complete — is implemented in `backend/src/core/agent/`
   (`orchestrator.py`, `loop.py`, `goal_interpreter.py`, `task_state.py`,
   `verify.py`, `post_execution_verifier.py`, `synthesizer.py`) and driven by
   `core.agent_runtime.AgentRuntime`. Many of the spec's principles are already
   realized as accepted decisions — see ADR-33 (parent-owned init), ADR-34
   (realtime workspace contract), ADR-36/37/38/42 (the Thinker as a silent
   mid-loop analyst), ADR-43 (tools as bounded helpers, not agents), ADR-45/46
   (execute is opt-in; uncertain classification resolves to a bounded direct
   answer — the spec's "don't fake autonomy / don't drag into a loop it didn't
   ask for" principle).

2. **Delegation is already built — ahead of this spec's roadmap.** The codebase
   ships `backend/src/core/agent/delegation.py`, `tools/delegate.py`, and
   `tools/delegate_parallel.py` (262 references), and `docs/ARCHITECTURE.md`
   advertises `delegate / delegate_parallel → isolated specialized child agents`.
   Per this spec (§36) those capabilities belong to a **later** phase. This is a
   genuine divergence, not a doc error. It is recorded as **ADR-47** and flagged
   as a backlog item for the user to steer — the decision to make is whether the
   existing delegation surface should be (a) kept dormant/unadvertised until the
   single-agent foundation is proven, or (b) removed to match the spec, or
   (c) treated as the point where LocalMind consciously moves past this phase.
   **No delegation code was changed by the documentation session** that captured
   this spec.

Everything from here down is the author's specification, verbatim.

---

## 1. Purpose

The current development phase is focused exclusively on building a **fully functional Parent Agent**.

The Parent Agent is the root and currently only agent in the system. It must be capable of receiving a user objective, understanding what needs to be accomplished, planning the required work, using available tools, observing the results of its actions, evaluating progress, recovering from failures, and completing the objective according to clearly defined success criteria.

**Specialist agents, sub-agents, delegation, and multi-agent orchestration are explicitly out of scope for this phase.**

Those capabilities may be introduced later, after the Parent Agent has demonstrated reliable autonomous execution.

The immediate goal is therefore not to build a multi-agent system.

The immediate goal is to build a **strong single-agent runtime** that can later become the foundation for a multi-agent system.

---

# 2. Current Architectural Position

The system currently contains one autonomous agent:

```text
                         USER
                           │
                           ▼
                  ┌─────────────────┐
                  │   PARENT AGENT  │
                  │                 │
                  │ Understand      │
                  │ Diagnose        │
                  │ Plan            │
                  │ Execute         │
                  │ Observe         │
                  │ Assess          │
                  │ Recover         │
                  │ Complete        │
                  └────────┬────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
           CONTEXT       MEMORY        TOOLS
```

The Parent Agent is responsible for the complete execution lifecycle.

There is currently no:

- Manager Agent above it
- Specialist Agent below it
- Agent delegation layer
- Multi-agent coordinator
- Agent-to-agent communication
- Specialist routing
- Agent hierarchy

The term **Parent Agent** describes its architectural role as the root agent, not an indication that child agents already exist.

---

# 3. Core Principle

The Parent Agent must be treated as an **autonomous executor**, not merely as a conversational LLM.

A conventional chatbot generally follows:

```text
User → Question → Model → Answer
```

The Parent Agent should instead operate as:

```text
User Goal
   ↓
Understand
   ↓
Diagnose
   ↓
Plan
   ↓
Act
   ↓
Observe
   ↓
Assess
   ↓
Iterate if necessary
   ↓
Verify
   ↓
Complete
```

The distinction is important.

The Parent Agent should not assume that producing a response means the task is complete.

**Completion must be determined by the outcome of the task.**

---

# 4. Definition of a Fully Functional Parent Agent

The Parent Agent is considered functionally complete for this phase when it can reliably perform the following lifecycle:

1. Receive a user objective.
2. Understand the intended outcome.
3. Identify relevant constraints.
4. Determine whether clarification is required.
5. Establish a Definition of Done.
6. Determine what information is required.
7. Inspect available context and memory.
8. Identify appropriate available tools.
9. Formulate an execution plan.
10. Execute the plan incrementally.
11. Observe the result of each action.
12. Update its understanding based on observations.
13. Detect failures and unexpected results.
14. Recover through retry, adjustment, or replanning.
15. Verify the final result against the Definition of Done.
16. Stop when the objective is actually satisfied.
17. Report the outcome clearly to the user.

This creates the fundamental autonomous loop:

```text
GOAL
 ↓
UNDERSTAND
 ↓
PLAN
 ↓
ACT
 ↓
OBSERVE
 ↓
ASSESS
 ↓
 ┌───────────────┐
 │               │
 ▼               ▼
FAIL           SUCCESS
 │               │
 ▼               ▼
RECOVER       VERIFY
 │               │
 └──────►        ▼
             COMPLETE
```

---

# 5. Parent Agent Responsibilities

The Parent Agent should have a clearly defined responsibility boundary.

## 5.1 Understand

The agent must determine what the user actually wants.

It should distinguish between:

- the literal request
- the intended outcome
- constraints
- preferences
- required inputs
- implied requirements
- optional versus mandatory work

The agent should not blindly execute ambiguous instructions.

If an important parameter is missing, it should determine whether it can safely infer it or whether clarification is necessary.

---

## 5.2 Diagnose

The agent should identify the actual problem before deciding how to solve it.

For example:

```text
User:
"My application is broken."

```

The agent should not immediately begin changing code.

It should determine:

```text
What application?
What is broken?
What changed?
What error occurs?
What is the expected behavior?
What evidence is available?
```

Diagnosis prevents premature execution.

---

## 5.3 Establish the Objective

Every meaningful task should have an explicit objective.

Conceptually:

```text
Objective:
What outcome must exist when the task is complete?
```

The objective should describe the **destination**, not unnecessarily prescribe every implementation step.

This allows the Parent Agent to determine the most appropriate execution path.

---

# 6. Definition of Done

A major requirement of the Parent Agent is a **Definition of Done (DoD)**.

The agent should not determine completion simply because:

- a tool returned successfully
- a model generated an answer
- a file was modified
- a command exited without an error
- an intermediate step succeeded

Instead:

> **Done means the required outcome has been achieved and verified against the task's success criteria.**

A useful conceptual structure is:

```text
OBJECTIVE
    ↓
SUCCESS CRITERIA
    ↓
EXECUTION
    ↓
VERIFICATION
    ↓
DONE
```

For example:

```text
Objective:
Fix the configuration issue.

Definition of Done:
The application starts successfully using the corrected configuration
and the affected functionality operates as expected.
```

The Definition of Done should be measurable whenever possible.

---

# 7. Planning

The Parent Agent should be capable of transforming an objective into an execution plan.

The plan should answer:

- What needs to happen?
- What information is needed?
- Which actions are required?
- What dependencies exist?
- Which steps can be performed independently?
- Which steps depend on previous results?
- What should be verified after each significant action?
- What should happen if a step fails?

A plan should be treated as **dynamic**, not immutable.

The initial plan is a hypothesis about how the task can be completed.

Actual observations may require the Parent Agent to modify it.

Therefore:

```text
Initial Plan
     ↓
Execute
     ↓
Observe
     ↓
Plan still valid?
   ┌───────┴───────┐
  YES              NO
   │                │
   ▼                ▼
Continue         Replan
```

---

# 8. Planning Versus Execution

The Parent Agent should distinguish between:

### Planning

Determining what should be done.

### Execution

Actually performing the action.

### Observation

Understanding what happened after execution.

### Assessment

Determining whether the result moves the task toward completion.

These should not be treated as one undifferentiated model response.

The conceptual cycle is:

```text
PLAN → ACTION → OBSERVATION → ASSESSMENT
```

This separation provides the foundation for reliable autonomous behavior.

---

# 9. Tool Usage

Tools are the Parent Agent's means of interacting with the environment.

The agent should not treat tools as simple functions that are called whenever convenient.

It should reason about:

- whether a tool is necessary
- which tool is appropriate
- what input the tool requires
- whether the action is safe
- what result is expected
- what actually happened
- what should happen next

The lifecycle should therefore be:

```text
Need identified
      ↓
Tool selected
      ↓
Tool parameters determined
      ↓
Tool executed
      ↓
Result received
      ↓
Result interpreted
      ↓
State updated
      ↓
Next action determined
```

---

# 10. Tool Result Interpretation

A successful tool call does not necessarily mean a successful task step.

For example:

```text
Tool:
Command executed successfully.
```

The Parent Agent still needs to determine:

```text
Did the command produce the expected result?
```

Therefore tool output must be treated as **observational evidence**, not automatically as truth.

The Parent Agent should inspect:

- success/failure status
- returned data
- errors
- warnings
- side effects
- unexpected output
- changes to the environment

This distinction is essential for autonomous systems.

---

# 11. Context

The Parent Agent should have access to the context required to make informed decisions.

Context should answer:

> What does the agent need to know right now to perform this task correctly?

Relevant context may include:

- current conversation
- task objective
- previous actions
- tool results
- project information
- user preferences
- active constraints
- relevant documents
- current environment state

Context should be **relevant**, rather than indiscriminately feeding everything available into the model.

More context is not automatically better context.

---

# 12. Context Management

The Parent Agent must avoid uncontrolled context growth.

Long-running execution can produce:

```text
User request
↓
Planning
↓
Tool 1
↓
Tool 2
↓
Tool 3
↓
Tool 4
↓
Tool 5
↓
Tool 6
↓
...
```

Eventually the context can become unnecessarily large and noisy.

The system should therefore distinguish between:

- active context
- historical context
- persistent memory
- execution state
- temporary tool output
- summarized information

The Parent Agent should receive the information necessary for the current decision without continuously carrying irrelevant historical material.

---

# 13. Memory

Memory and context should not be treated as identical.

### Context

Information needed for the current reasoning process.

### Memory

Information retained because it may be useful in future interactions.

Examples of potential memory:

- previous decisions
- established preferences
- recurring workflow information
- important project facts
- successful approaches
- persistent user instructions

The Parent Agent should not automatically save every piece of information.

Memory should have a reason to exist.

---

# 14. Execution State

The Parent Agent needs an explicit understanding of its current execution state.

Conceptually:

```text
Task State

Objective
Definition of Done
Constraints
Current Plan
Current Step
Completed Steps
Pending Steps
Failed Steps
Observations
Decisions
Relevant Context
Required Verification
Final Status
```

This allows the agent to answer:

> "Where am I in this task?"

without reconstructing the entire workflow from raw conversation history.

---

# 15. State Transitions

The Parent Agent should operate through meaningful execution states.

A conceptual lifecycle is:

```text
RECEIVED
   ↓
UNDERSTANDING
   ↓
DIAGNOSING
   ↓
PLANNING
   ↓
EXECUTING
   ↓
OBSERVING
   ↓
ASSESSING
   │
   ├───────────────┐
   │               │
   ▼               ▼
CONTINUE         RECOVER
   │               │
   │               ▼
   │             REPLAN
   │               │
   └───────┬───────┘
           ▼
       VERIFYING
           │
      ┌────┴────┐
      ▼         ▼
    DONE       FAIL
      │         │
      ▼         ▼
   REPORT     RECOVER/
              ESCALATE
```

The exact implementation can evolve, but the conceptual state model should remain clear.

---

# 16. Assessment

Assessment is what separates an agent from a simple sequential automation script.

After an action, the Parent Agent should ask:

1. What happened?
2. Was the result expected?
3. Did the action advance the objective?
4. Did it introduce a new problem?
5. Does the current plan remain valid?
6. Is additional action required?

This creates a feedback loop:

```text
ACTION
  ↓
RESULT
  ↓
ASSESS
  ↓
DECIDE
  ↓
NEXT ACTION
```

---

# 17. Self-Correction

The Parent Agent should be capable of recognizing when its approach is not working.

Failure should not automatically terminate the task.

Depending on the situation, the agent may:

- retry the same action
- change parameters
- inspect additional information
- choose a different available tool
- revise the plan
- undo a failed action where possible
- request user input
- stop safely

The important distinction is between **productive recovery** and uncontrolled looping.

---

# 18. Retry and Loop Protection

Autonomy requires loop protection.

The Parent Agent must not repeatedly perform the same unsuccessful action indefinitely.

A failed step should provide new information.

Conceptually:

```text
Attempt 1
   ↓
Failure
   ↓
Diagnosis
   ↓
Changed approach
   ↓
Attempt 2
   ↓
Failure
   ↓
Reassessment
```

If repeated attempts do not produce meaningful progress, the agent should stop or escalate rather than continue indefinitely.

---

# 19. Asking the User for Clarification

Autonomy does not mean refusing to ask questions.

The Parent Agent should ask the user when:

- a critical requirement is ambiguous
- an action has significant consequences and authorization is unclear
- multiple interpretations are materially different
- required information cannot be obtained through available tools
- continuing would require an unsafe assumption

However, it should avoid unnecessary clarification.

If a reasonable low-risk assumption can be made, the agent may proceed while recording the assumption.

---

# 20. Guardrails

The Parent Agent should have explicit boundaries.

Guardrails should define:

- actions it may perform
- actions requiring confirmation
- actions it must never perform
- resources it may access
- resources outside its scope
- maximum execution limits
- failure behavior
- escalation conditions

A useful principle is:

> **Autonomy must operate inside a permission boundary.**

The model should not be given unrestricted authority simply because it can technically invoke a tool.

---

# 21. Trust in Stages

Autonomy should be introduced progressively.

A useful maturity model is:

### Stage 0 — Observe

The Parent Agent can inspect information but cannot modify the environment.

### Stage 1 — Recommend

The Parent Agent proposes actions but does not execute them.

### Stage 2 — Draft

The Parent Agent prepares changes for approval.

### Stage 3 — Controlled Execute

The Parent Agent can execute approved low-risk operations.

### Stage 4 — Autonomous Execute

The Parent Agent can execute permitted operations without continuous approval.

### Stage 5 — Autonomous Recovery

The Parent Agent can execute, verify, recover, and continue independently within defined limits.

The current system should not assume Stage 5 simply because the model is capable of generating autonomous-looking reasoning.

Trust must be earned through observed reliability.

---

# 22. Human-in-the-Loop

Human approval should be treated as a system capability rather than as a failure of the agent.

For example:

```text
Agent:
"I need to modify these files."

        ↓

Approval Required

        ↓

User approves

        ↓

Agent executes

        ↓

Agent verifies
```

Over time, trusted low-risk operations can become autonomous while higher-risk operations continue to require approval.

---

# 23. Agent Identity

The Parent Agent needs a stable identity.

Identity should establish:

- what the agent is
- its primary purpose
- its responsibilities
- its scope
- its operating principles
- its limitations

The identity should prevent the agent from drifting into arbitrary roles.

For example, the Parent Agent should understand that it is an autonomous task executor and orchestrator of **currently available capabilities**, not an unrestricted system administrator.

---

# 24. Behavioral Rules

The Parent Agent should also have behavioral rules.

These govern how it operates rather than merely what it is.

Examples of behavioral principles include:

- understand before acting
- prefer evidence over assumptions
- verify important results
- preserve task state
- avoid unnecessary actions
- do not claim success without verification
- recover from recoverable failures
- ask when critical information is missing
- respect permission boundaries
- stop when the Definition of Done is satisfied

These rules form the agent's operational discipline.

---

# 25. The Parent Agent Should Not Fake Autonomy

A major architectural risk is creating an agent that **looks autonomous in its response but is actually just generating a predetermined chain of actions**.

For example:

```text
I'll inspect the project.
I'll fix the problem.
I'll run tests.
I'll verify everything.
```

That is not sufficient.

Actual autonomy requires the environment to provide observations between actions:

```text
Plan
 ↓
Action
 ↓
Actual result
 ↓
Interpret result
 ↓
Decide next action
```

The next action must be influenced by what actually happened.

---

# 26. Dynamic Planning

The Parent Agent should not be forced to follow a static workflow when reality changes.

Suppose the plan is:

```text
1. Inspect
2. Modify
3. Test
4. Verify
```

If inspection reveals that the presumed cause is incorrect, the agent should be able to produce:

```text
Original assumption invalid.

New evidence:
...

Revised plan:
1. Investigate alternative cause
2. Inspect related component
3. Modify correct component
4. Test
5. Verify
```

This is a fundamental agent capability.

---

# 27. The Agent's Core Decision Loop

The Parent Agent's central runtime can conceptually be expressed as:

```text
while objective_not_complete:

    understand_current_state()

    determine_next_action()

    execute_action()

    observe_result()

    update_state()

    assess_progress()

    if blocked:
        recover_or_escalate()

    if definition_of_done_satisfied:
        verify_and_complete()
```

This is a conceptual model, not a requirement to implement the runtime literally this way.

The important part is the **closed feedback loop**.

---

# 28. Error Handling

Errors should be classified rather than treated uniformly.

Potential categories include:

### Transient errors

Examples:

- temporary network failure
- timeout
- temporary service unavailability

Potential response:

```text
Retry with controlled limits.
```

### Input errors

Examples:

- invalid parameter
- missing required value

Potential response:

```text
Correct input or request clarification.
```

### Environment errors

Examples:

- missing dependency
- inaccessible resource
- unavailable file

Potential response:

```text
Inspect environment and determine recovery path.
```

### Logical errors

The Parent Agent's assumption or plan is incorrect.

Potential response:

```text
Reassess and replan.
```

### Permission errors

The agent lacks authorization.

Potential response:

```text
Stop or request authorization.
```

### Irrecoverable errors

The task cannot safely continue.

Potential response:

```text
Stop and report the actual state.
```

---

# 29. Completion

Completion should require more than an absence of errors.

The Parent Agent should distinguish:

```text
Action succeeded
```

from:

```text
Objective succeeded
```

For example:

```text
Tool successfully created a file.
```

does not mean:

```text
The user's requested functionality is complete.
```

The Parent Agent must evaluate the **outcome**.

---

# 30. Final Verification

Before declaring completion, the Parent Agent should perform an appropriate verification step.

The verification method depends on the task.

Examples:

- run tests
- inspect generated files
- compare expected versus actual state
- verify a requested resource exists
- validate data
- inspect command output
- confirm a workflow completed
- check the Definition of Done

The agent should be able to state internally:

```text
Definition of Done:
Satisfied.

Evidence:
...

Verification:
...

Status:
Complete.
```

---

# 31. User-Facing Reporting

The internal execution process may be complex, but the final response should be clear.

The Parent Agent should report:

1. What was accomplished.
2. Any important findings.
3. Whether the Definition of Done was satisfied.
4. Any limitations or unresolved issues.
5. Relevant next steps, if any.

It should not expose internal execution noise simply because it occurred.

A successful autonomous workflow should produce a useful outcome, not an unnecessary transcript of every internal decision.

---

# 32. Separation of Internal State and User Conversation

The Parent Agent should distinguish between:

### Internal execution state

Used by the agent/runtime to manage the task.

### User-facing conversation

Used to communicate with the user.

Not every internal state transition needs to be shown to the user.

This becomes increasingly important as workflows become longer and more autonomous.

---

# 33. Observability

A reliable Parent Agent should be observable.

The system should make it possible to determine:

- what objective was received
- what plan was created
- which actions were executed
- which tools were used
- what results were returned
- what failures occurred
- what decisions were made
- how many iterations occurred
- why the agent stopped
- whether the Definition of Done was satisfied

This is important for debugging and evaluating agent reliability.

---

# 34. Execution History

Each execution should conceptually produce a history:

```text
Task
 ↓
Objective
 ↓
Plan
 ↓
Step 1
 ↓
Observation
 ↓
Step 2
 ↓
Observation
 ↓
Replan
 ↓
Step 3
 ↓
Verification
 ↓
Completion
```

This history provides the evidence required to understand what the agent actually did.

It should not be confused with long-term memory.

Execution history describes **this task**.

Memory describes information potentially useful **beyond this task**.

---

# 35. The Rule of R

Before making a workflow highly autonomous, evaluate whether it is worth automating.

The workflow should ideally be:

### Repetitive

It happens often enough to justify automation.

### Rules-based

The inputs, constraints, and desired outcomes are sufficiently understandable.

### Return on Time

The time and effort saved through automation justify building and maintaining the agent.

This prevents building elaborate agents for tasks that are better handled through simple deterministic automation.

---

# 36. What the Parent Agent Should NOT Do Yet

The following are deliberately excluded from the current phase:

### Specialist agents

No dedicated research agent, coding agent, reviewer agent, etc.

### Agent delegation

The Parent does not delegate work to other agents.

### Multi-agent communication

No agent-to-agent messaging.

### Agent hierarchy

No:

```text
Parent
 └── Manager
      └── Specialist
```

### Agent marketplace/capability routing

Not required yet.

### Parallel specialist execution

Not required yet.

### Specialist-specific memories

Not required yet.

### Multi-agent consensus

Not required yet.

These are future expansion capabilities.

---

# 37. Future Evolution

Once the Parent Agent is reliable, the architecture can evolve without changing its fundamental responsibilities.

Current:

```text
USER
  │
  ▼
PARENT AGENT
  │
  ├── Context
  ├── Memory
  └── Tools
```

Future:

```text
USER
  │
  ▼
PARENT AGENT
  │
  ├── Research Specialist
  ├── Coding Specialist
  ├── Review Specialist
  ├── Data Specialist
  └── Other Specialists
          │
          ▼
        Tools
```

The Parent Agent would then gain an additional capability:

> Determine when a task should be delegated and coordinate the resulting work.

But this should be added **after** the single-agent foundation is stable.

---

# 38. Architectural Evolution Principle

The future multi-agent architecture should be an **extension of the Parent Agent**, not a replacement for it.

The Parent Agent should already possess:

```text
Goal understanding
Planning
State management
Tool execution
Observation
Assessment
Recovery
Verification
```

Later, delegation becomes another available capability:

```text
Parent
   │
   ├── Execute directly
   │
   └── Delegate
          │
          ├── Specialist A
          ├── Specialist B
          └── Specialist C
```

The Parent therefore remains the root decision-making component.

---

# 39. Development Priority

The current implementation should prioritize functionality in this order:

## Phase 1 — Objective Understanding

The Parent can correctly interpret user requests.

## Phase 2 — Context Acquisition

The Parent can determine and retrieve the information required for execution.

## Phase 3 — Planning

The Parent can produce an appropriate execution strategy.

## Phase 4 — Tool Execution

The Parent can invoke available capabilities and process their results.

## Phase 5 — State Management

The Parent can maintain reliable execution state.

## Phase 6 — Assessment

The Parent can determine whether actions produced useful results.

## Phase 7 — Recovery

The Parent can respond intelligently to failures.

## Phase 8 — Verification

The Parent can determine whether the Definition of Done has been satisfied.

## Phase 9 — Controlled Autonomy

The Parent can execute increasingly larger portions of workflows without human intervention.

## Phase 10 — Reliability

The system is evaluated across representative workflows and failure scenarios.

Only after these phases are sufficiently mature should specialist agents be introduced.

---

# 40. Parent Agent Quality Criteria

The Parent Agent should ultimately be evaluated on:

### Goal accuracy

Does it correctly understand what the user wants?

### Planning quality

Does its plan represent a sensible route toward the objective?

### Tool selection

Does it use appropriate tools rather than unnecessary ones?

### Execution reliability

Does it perform actions correctly?

### Observation quality

Does it correctly interpret actual tool/environment results?

### Adaptability

Can it change course when assumptions prove wrong?

### Recovery

Can it recover from reasonable failures?

### Verification

Can it distinguish successful actions from successful outcomes?

### State integrity

Does it maintain an accurate representation of task progress?

### Safety

Does it respect permission and execution boundaries?

### Efficiency

Does it avoid unnecessary reasoning, actions, tool calls, and context consumption?

### Completion accuracy

Does it stop when the objective is genuinely complete?

---

# 41. The Fundamental Agent Contract

The Parent Agent should ultimately operate according to a simple contract:

```text
I receive an objective.

I determine what the objective actually requires.

I identify the information and capabilities necessary to accomplish it.

I create an execution plan.

I execute the plan through available capabilities.

I observe what actually happens.

I update my understanding and state.

If the approach fails, I recover or replan when possible.

I verify the result against the Definition of Done.

I do not claim completion without sufficient evidence.

If I cannot safely or reliably complete the objective,
I explain the actual state and what prevents completion.
```

This contract captures the essential behavior of the current system.

---

# 42. Final Target Architecture for the Current Phase

The final architecture for this phase should remain intentionally simple:

```text
                         ┌──────────────────────┐
                         │         USER         │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │    PARENT AGENT      │
                         │                      │
                         │  Goal Understanding  │
                         │          ↓           │
                         │      Diagnosis       │
                         │          ↓           │
                         │       Planning       │
                         │          ↓           │
                         │      Execution       │
                         │          ↓           │
                         │      Observation     │
                         │          ↓           │
                         │      Assessment      │
                         │          ↓           │
                         │       Recovery       │
                         │          ↓           │
                         │      Verification    │
                         │          ↓           │
                         │      Completion      │
                         └──────────┬───────────┘
                                    │
             ┌──────────────────────┼──────────────────────┐
             │                      │                      │
             ▼                      ▼                      ▼
       ┌───────────┐          ┌───────────┐          ┌───────────┐
       │  CONTEXT  │          │  MEMORY   │          │   TOOLS   │
       └───────────┘          └───────────┘          └───────────┘
```

There should be **no specialist layer at this point**.

The Parent Agent is the entire autonomous intelligence layer.

---

# 43. Success Condition for This Phase

The phase is successful when the Parent Agent can receive a sufficiently complex objective and autonomously progress through:

```text
                    USER OBJECTIVE
                          │
                          ▼
                    UNDERSTAND
                          │
                          ▼
                      DIAGNOSE
                          │
                          ▼
                       PLAN
                          │
                          ▼
                       ACT
                          │
                          ▼
                     OBSERVE
                          │
                          ▼
                     ASSESS
                     /       \
                  FAIL       PASS
                   │           │
                   ▼           ▼
                RECOVER     VERIFY
                   │           │
                   └─────┐     │
                         │     ▼
                         └──► DONE
```

with:

- reliable state
- appropriate context
- controlled tool access
- meaningful observation
- dynamic replanning
- bounded retries
- explicit verification
- clear completion criteria
- safe escalation when blocked

Only after this capability is stable should the system move into multi-agent architecture.

---

# 44. Strategic Direction

The long-term architecture can eventually become a multi-agent ecosystem, but that should not influence the current implementation unnecessarily.

The correct progression is:

```text
                    CURRENT
                       │
                       ▼
              ┌─────────────────┐
              │  PARENT AGENT   │
              │  Fully capable  │
              │  single agent   │
              └────────┬────────┘
                       │
                       │ proven reliable
                       ▼
              ┌─────────────────┐
              │   DELEGATION    │
              │   CAPABILITY    │
              └────────┬────────┘
                       │
                       ▼
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      Specialist    Specialist    Specialist
          │            │            │
          └────────────┼────────────┘
                       ▼
              MULTI-AGENT SYSTEM
```

The principle is straightforward:

> **First make one agent genuinely autonomous. Then make it capable of coordinating other agents.**

That keeps the current architecture focused, testable, and understandable while preserving a clean path toward the multi-agent system you intend to build later.