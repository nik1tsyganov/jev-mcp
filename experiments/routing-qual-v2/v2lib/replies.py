"""Reply generators for the helper's native classifier request (controls and baselines).

Every generator reads the exact prepared request (`requestJSON`) and answers its
questions in the Jev wire shape the helper parses: choice answers carry full
`probabilities`; yes/no answers are `{"type": "noul", "noul": p}`. Controls are
labelled by `model` only through the backend identity they are replayed under;
they are never classifier evidence.
"""
import json
import random
import re

JEV_MODEL = "jev-1.13.0"
LAYA_MODEL = "laya-mlx-0476785"
MALFORMED = ("bool", "sum", "missing", "extra", "unknown_label", "nan", "non_json")

# Deterministic keyword baselines, written from the helper's own criteria text only.
FAMILY_RULES = [
    ("mechanical", r"\b(rename|bump|migrate|reformat|every file|across all|bulk|replace all)\b"),
    ("study", r"\b(study|exam|homework|lecture|flashcard|practice|course)\b"),
    ("research", r"\b(research|compare sources|literature|survey|find out|which vendors)\b"),
    ("analysis", r"\b(analy[sz]e|audit|investigate|why does|root cause|review)\b"),
    ("coding", r"\b(implement|fix|bug|refactor|add (a )?test|endpoint|function|swift|python|code)\b"),
]
CLASS_RULES = [
    ("security-sensitive", r"\b(auth|login|session|token|secret|password|payment|oauth|permission)\b"),
    ("bulk-mechanical", r"\b(rename|bump|migrate|reformat|bulk)\b"),
    ("debug-mystery", r"\b(flaky|intermittent|crash|root cause|why does|unexplained)\b"),
    ("architecture-planning", r"\b(design|architecture|plan the|interfaces)\b"),
    ("research-synthesis", r"\b(research|sources|compare|literature)\b"),
    ("long-context-analysis", r"\b(whole codebase|all files|large corpus|entire repo)\b"),
    ("test-verification", r"\b(verify|test suite|coverage|regression)\b"),
    ("study-coding", r"\b(homework|exam|course|study)\b"),
    ("standard-feature", r"\b(add|implement|fix|feature)\b"),
]


def questions_of(request_json):
    return json.loads(request_json)["questions"]


def _choice(labels, chosen, p=1.0):
    others = [label for label in labels if label != chosen]
    rest = (1.0 - p) / len(others) if others else 0.0
    probs = {label: (p if label == chosen else rest) for label in labels}
    return {"type": "choice", "choice": chosen, "probabilities": probs}


def _reply(answers, model, input_tokens=0):
    return json.dumps({"model": model, "answers": answers,
                       "usage": {"input_tokens": input_tokens, "output_tokens": 0}}, allow_nan=True)


def answer_with(request_json, label_for, noul_for, model=JEV_MODEL, p=1.0):
    answers = {}
    for qid, q in questions_of(request_json).items():
        if q["type"] == "choice":
            labels = list(q["criteria"])
            chosen = label_for(qid, labels)
            if chosen not in labels:
                # An unanswerable label (for example 'unclear' absent in Conclave) spreads mass.
                answers[qid] = {"type": "choice", "choice": labels[0],
                                "probabilities": {label: 1.0 / len(labels) for label in labels}}
            else:
                answers[qid] = _choice(labels, chosen, p)
        else:
            answers[qid] = {"type": "noul", "noul": float(noul_for(qid))}
    return _reply(answers, model)


def gold_nouls(gold):
    roles = set(gold.get("role_needs") or [])
    flags = gold.get("flags", {})
    def noul(qid):
        if qid.startswith("role_"):
            return 1.0 if qid.removeprefix("role_") in roles else 0.0
        return float(bool(flags.get("security" if qid == "security_task" else "school")))
    return noul


def oracle(request_json, gold, model=JEV_MODEL):
    return answer_with(request_json, lambda qid, labels: gold.get("preferred_label") or "unclear", gold_nouls(gold), model)


def anti(request_json, gold, model=JEV_MODEL):
    def wrong(qid, labels):
        bad = [label for label in labels if label not in gold.get("acceptable_labels", []) and label != "unclear"]
        return bad[0] if bad else labels[0]
    return answer_with(request_json, wrong, lambda qid: 0.0, model)


def constant(request_json, family=None, task_class=None, model=JEV_MODEL):
    return answer_with(request_json, lambda qid, labels: family if qid == "family" else task_class,
                       lambda qid: 0.0, model)


def shuffled_oracle(request_json, gold, seed, model=JEV_MODEL):
    """Gold distribution with the label names permuted (seeded per case)."""
    rng = random.Random(f"{seed}:{gold['id']}")
    answers = json.loads(oracle(request_json, gold, model))["answers"]
    for qid, answer in answers.items():
        if answer["type"] == "choice":
            labels = list(answer["probabilities"])
            values = [answer["probabilities"][label] for label in labels]
            rng.shuffle(values)
            answer["probabilities"] = dict(zip(labels, values))
            answer["choice"] = max(answer["probabilities"], key=answer["probabilities"].get)
    return _reply(answers, model)


def random_reply(request_json, seed, model=JEV_MODEL):
    rng = random.Random(seed)
    return answer_with(request_json, lambda qid, labels: rng.choice(labels), lambda qid: rng.random(), model)


def _keyword(text, rules, default):
    lowered = text.lower()
    for label, pattern in rules:
        if re.search(pattern, lowered):
            return label
    return default


def matrix(request_json, model=JEV_MODEL):
    state = json.loads(request_json)["state"]
    text = state.get("task") or state.get("brief") or ""
    return answer_with(request_json,
                       lambda qid, labels: _keyword(text, FAMILY_RULES, "general") if qid == "family"
                       else _keyword(text, CLASS_RULES, "standard-feature"),
                       lambda qid: 0.0, model)


def manual(request_json, model=JEV_MODEL):
    return constant(request_json, family="coding", task_class="standard-feature", model=model)


def malformed(request_json, variant, model=JEV_MODEL):
    answers = json.loads(constant(request_json, "coding", "standard-feature", model))["answers"]
    choice_qid = next(qid for qid, a in answers.items() if a["type"] == "choice")
    probs = answers[choice_qid]["probabilities"]
    first = next(iter(probs))
    if variant == "bool":
        probs[first] = True
    elif variant == "sum":
        probs[next(label for label, p in probs.items() if p == 0)] = 0.2  # total becomes 1.2
    elif variant == "missing":
        answers.pop(choice_qid)
    elif variant == "extra":
        answers["unexpected"] = {"type": "noul", "noul": 1.0}
    elif variant == "unknown_label":
        probs["not-a-label"] = probs.pop(first)
    elif variant == "nan":
        probs[first] = float("nan")
    elif variant == "non_json":
        return "this is not JSON"
    return _reply(answers, model)
