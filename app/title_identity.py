"""Single directory-entry validation for isolated title rehearsals."""


def validate_title_folder(folder):
    """Allow one literal folder name, never a path or traversal component."""
    if (not isinstance(folder, str) or not folder.strip() or folder in (".", "..")
            or "/" in folder or chr(92) in folder
            or any(ord(char) < 32 or ord(char) == 127 for char in folder)):
        raise ValueError("Single safe title folder required")
    return folder
