import time
from enum import Enum

# -------------------------
# CONFIG (hard bounds)
# -------------------------

MAX_ESCALATION_LEVEL = 3
DECISION_REPEAT_THRESHOLD = 2
POLL_INTERVAL_SECONDS = 300  # 5 minutes

# -------------------------
# STATES
# -------------------------

class EscalationLevel(Enum):
    PULL_ONLY = 0
    AUTO_SCOUT = 1
    DRAFT_ONLY = 2
    FORCE_SINGLE_ACTION = 3

# -------------------------
# SYSTEM STATE (no memory)
# -------------------------

state = {
    "escalation_level": EscalationLevel.PULL_ONLY,
    "decision_counter": {},
}

# -------------------------
# CORE INVARIANTS
# -------------------------

def record_decision(decision_key: str):
    count = state["decision_counter"].get(decision_key, 0) + 1
    state["decision_counter"][decision_key] = count

    if count >= DECISION_REPEAT_THRESHOLD:
        escalate()

def escalate():
    current = state["escalation_level"].value
    if current < MAX_ESCALATION_LEVEL:
        state["escalation_level"] = EscalationLevel(current + 1)
        reset_decisions()

def collapse():
    state["escalation_level"] = EscalationLevel.PULL_ONLY
    reset_decisions()

def reset_decisions():
    state["decision_counter"].clear()

# -------------------------
# DATA SOURCES (STUBS)
# -------------------------

def fetch_gumtree():
    """
    Return list of dicts:
    { id, title, price, location }
    """
    return []

def fetch_marketplace():
    return []

# -------------------------
# MECHANICAL FILTERS
# -------------------------

def is_mispriced(item):
    if item["price"] == 0:
        return True
    if item["price"] < 0.25 * estimated_resale(item):
        return True
    return False

def estimated_resale(item):
    # deliberately dumb and fixed
    return 60

# -------------------------
# ACTION GENERATION
# -------------------------

def generate_actions(items):
    actions = []

    for item in items:
        if is_mispriced(item):
            actions.append({
                "type": "pickup_candidate",
                "item": item
            })

    return actions

# -------------------------
# ESCALATION BEHAVIOUR
# -------------------------

def handle_actions(actions):
    level = state["escalation_level"]

    if not actions:
        return

    if level == EscalationLevel.PULL_ONLY:
        # Human notices opportunity or not
        record_decision("send_message")

    elif level == EscalationLevel.AUTO_SCOUT:
        # Expanded search already handled upstream
        record_decision("send_message")

    elif level == EscalationLevel.DRAFT_ONLY:
        draft_message(actions[0])
        record_decision("confirm_send")

    elif level == EscalationLevel.FORCE_SINGLE_ACTION:
        send_message(actions[0])
        collapse()

# -------------------------
# COMMUNICATION (STUBS)
# -------------------------

def draft_message(action):
    item = action["item"]
    print(f"DRAFT: Hi, I can pick up today. Is this still available? ({item['title']})")

def send_message(action):
    item = action["item"]
    print(f"SENT: Message sent for {item['title']}")

# -------------------------
# MAIN LOOP
# -------------------------

def run():
    while True:
        gumtree_items = fetch_gumtree()
        marketplace_items = fetch_marketplace()

        all_items = gumtree_items + marketplace_items
        actions = generate_actions(all_items)

        handle_actions(actions)

        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    run()
