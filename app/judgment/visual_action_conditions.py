"""视觉动作的固定判断条件；供运行时与请求适配器共用。"""

CANDIDATE_CONDITION = (
    "The specified original action targets the intended visible element, is within the stated task "
    "and permitted action class, and can proceed safely without handling any popup or other intervention.")
SCENE_CONDITION = (
    "The visible scene permits the specified task step without handling a popup or other intervention. "
    "This checks the scene only, not any future target coordinates.")
FRESHNESS_CONDITION = (
    "The proposed click point is still inside the same intended visible target in the latest frame, "
    "and that target remains identifiable, unobscured and usable for the specified current action. "
    "Compare the target and its immediate surrounding anchor first. "
    "Changes elsewhere matter only if they move or obscure the target, redirect input, "
    "change what this action would do, or require intervention before it. "
    "Unrelated news, advertisements, text updates or animation do not make this condition false. "
    "Evaluate current feasibility, not whether the whole page stayed unchanged.")

VISUAL_FIELD_FRESHNESS_CONDITION = (
    "The same specified ordinary readable text field remains focused, enabled, editable and unmasked, bound to the same native "
    "identity, value and selection. Using the bound native field evidence and before/after images, compare the field and its immediate "
    "surroundings first, including the declared changed_region. The field must still satisfy field_freshness_context.original_condition, "
    "and its target meaning and the intended effect of the original keyboard action must remain unchanged. Caret blink, focus or border "
    "styling, and auxiliary suggestions are permitted only when they do not obscure or obstruct the target or change that keyboard "
    "action's meaning or effect. Refuse if focus moves elsewhere, a selected suggestion changes what Enter would do, the field is "
    "obscured or unusable, field text, label, placeholder or selection changes, native identity or target meaning changes, or intervention "
    "is required. Do not infer safety from native value equality alone.")

VISUAL_INPUT_CLICKED_CONDITION = "The recorded click is inside the intended visible text input."

# 旧条件仅用于历史回执和显式兼容请求。
VISUAL_INPUT_READY_CONDITION = "The marked click is inside the intended visible text input and the field is usable for typing now."
VISUAL_REPLACEMENT_READY_CONDITION = "The intended text input is empty or its complete existing text is selected for replacement."
VISUAL_TEXT_VALUE_CONDITION = "The target field displays exactly the specified expected text."

# 旧条件保留给冻结回执及显式原生路线。
VISUAL_VALUE_CONDITION = (
    "The specified ordinary readable text field visibly has keyboard focus and its complete text exactly "
    "equals the expected text in the bound action context; no characters are hidden, clipped, masked or ambiguous.")
