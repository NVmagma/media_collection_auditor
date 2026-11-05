"""Lifecycle stage names and supported transitions."""
CLOCKS = {"Waiting": "first_seen", "Holding": "queued", "Removal": "in_removal", "Keep": "keep_seen"}

TRANSITIONS = {
    ("Waiting", "Holding"), ("Waiting", "Keep"),
    ("Holding", "Removal"), ("Holding", "Keep"), ("Removal", "Keep"),
}
