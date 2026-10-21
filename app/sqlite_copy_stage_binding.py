"""Explicit non-deleting copy transitions; no policy or activation authority."""
CLOCKS = {"transient": "first_seen", "holding": "queued", "keep": "keep_seen", "removal": "in_removal"}
TRANSITIONS = {("transient", "holding"), ("transient", "keep"),
               ("holding", "keep"), ("holding", "removal")}
