import os
from fastapi import FastAPI, HTTPException
from typing import Dict, Any, List

# --- CONFIGURATION (Must match the path in your auditor script) ---
# This is where the API knows WHERE to find the current state of the system.
STATE_FILE = "/app/logs/auditor_state.json" 

# The application instance
app = FastAPI(title="Media Collection Auditor API")


def load_current_state() -> Dict[str, Any]:
    """Loads the most up-to-date transactional state from disk."""
    try:
        with open(STATE_FILE, 'r') as f:
            # Important: The file must be consistently structured and locked during read.
            return json.load(f)
    except FileNotFoundError:
        # This is fine if the auditor hasn't run yet. Graceful failure.
        return {}
    except json.JSONDecodeError:
        # This is critical if the auditor crashes mid-write. Skip corrupted files.
        return {}


# ==============================================
# --- API ENDPOINTS (The Watchtower) ---
# ==============================================

@app.get("/status")
def get_current_status():
    """Endpoint to retrieve the current state of all tracked packages."""
    state = load_current_state()
    return {"status": "OK", "data": state}


@app.get("/purge_log")
def get_recent_actions():
    """Endpoint to view the log of actions taken (the history)."""
    # This function would pull a dedicated action log, but for now, we use the state.
    state = load_current_state()
    return {"status": "success", "actions": state.get("history", [])}


@app.post("/action/rescue/{package_id}")
def rescue_file(package_id: str):
    """
    ACTION ENDPOINT: This is the critical button. 
    It triggers the backend transaction to MOVE the file BEFORE it's gone.
    """
    # In a real system, this endpoint would signal the main collection_auditor.py 
    # process (via a dedicated message queue or signal file) to execute the move.
    print(f"[COMMAND RECEIVED] Attempting immediate rescue of {package_id}.")
    # Return success, confirming the command was received.
    return {"message": f"Rescue for {package_id} queued successfully."}


# --- Run the service using uvicorn ---
# Note: You won't run this file directly. The command line will handle it.

# If you are testing locally, use:
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
