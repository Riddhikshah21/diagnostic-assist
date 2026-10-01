# What the product actually is

## My understanding of the user

The main user would be the service dispatcher.

The dispatcher is usually speaking with a customer who has reported a machine problem. They need to understand what happened, decide what information the technician needs and consider which parts may be useful for the visit.

The customer would not use the first version directly. They would describe the problem and answer simple questions over the phone. The dispatcher would enter this information into the assistant.

The technician would receive the final handoff. They would still inspect the machine and confirm the real cause onsite.

## How the conversation works

The dispatcher starts by selecting the equipment type and entering the customer’s description in normal language. The description may be in English, German, French, Italian or a mixture of languages.

The system first shows what it understood and retrieves similar historical cases. The first useful evidence should appear within three seconds. Slower cause grouping or explanation may appear afterward.

The assistant shows a small number of possible causes together with the historical cases that support them. These are possibilities, not a final diagnosis.

If one missing detail could separate the possible causes, the assistant suggests one short follow-up question. The dispatcher asks the customer and records the answer. `Unknown` is always a valid response and is not treated as supporting evidence.

After receiving a useful answer, the system searches again with the updated information. Questions that require tools, measurements, technical knowledge or unsafe actions are left for the technician.

## What the dispatcher sees

The final handoff contains:

- a summary of the reported problem;
- the information collected during the call;
- a short list of possible causes;
- the historical cases supporting each possibility;
- the strength and amount of available evidence;
- useful checks for the technician;
- parts used in similar confirmed repairs.

The final product is intended to show a probability for each possible cause. However, the historical data does not contain confirmed root-cause labels. A vector similarity score or an LLM confidence value should not be presented as a diagnostic probability.

For the prototype, I would show a clearly named evidence estimate and the number of supporting cases. Calibrated probabilities would require a human-reviewed evaluation set or confirmed outcomes collected from future cases.

## When the conversation ends

The conversation ends when:

- the dispatcher has enough information to arrange the visit;
- the next useful check requires a technician;
- the customer cannot answer more useful questions;
- the historical evidence cannot narrow the issue further;
- the dispatcher decides to continue with a normal service visit.

I would not end the conversation only because one cause passed an arbitrary threshold. The available information may still be incomplete or incorrect.

## Example using case C-48211

For this walkthrough, I would treat `C-48211` as a new incoming case and remove it from the historical search results. This prevents the system from retrieving the answer directly.

The customer reports:

```text
Unit won't start at all. No lights on the control panel.
```

The dispatcher selects equipment type `CX-450` and enters the description.

The assistant confirms that it understood two symptoms:

- the unit will not start;
- the control panel has no power.

It then searches the remaining historical cases. Three relevant cases are:

- `C-48377`: the machine did not start and the display was blank. The technician replaced a failed main contactor.
- `C-48590`: the machine would not crank and the panel was dead. The technician found a loose and heavily corroded ground strap. The contactor tested correctly.
- `C-49040`: the machine would not power up because the battery had failed.

The assistant presents these as possible explanations:

| Possible cause | Evidence |
|---|---|
| Main contactor failure | Supported by `C-48377` |
| Loose or corroded ground connection | Supported by `C-48590` |
| Failed battery | Supported by `C-49040` |

The assistant does not claim that any of these is already confirmed.

One detail may help reduce the uncertainty, so it suggests:

> Has the battery been flat or needed charging recently?

If the customer says no, battery failure becomes less likely. If the customer does not know, the dispatcher records `Unknown`, and the ranking should not change based on that answer.

The remaining possibilities require an onsite electrical check. Asking the customer to measure voltage or inspect unsafe electrical connections would not be appropriate, so the assistant stops asking questions.

It prepares a handoff containing:

- CX-450 will not start;
- no lights are visible on the control panel;
- the customer reported no recent battery problem;
- similar cases involved a failed main contactor, a loose ground connection and a failed battery;
- the technician should check the battery, ground connection and main contactor;
- `CONTACTOR-M1` may be worth considering because it was used in a similar confirmed repair.

The part is presented as something to consider, not as proof that it will be required.

In the original `C-48211` case, the technician found that the main contactor coil was open and replaced `CONTACTOR-M1`. The assistant did not need to make this final diagnosis. Its value was finding relevant evidence, collecting one useful detail and giving the technician a better place to start.