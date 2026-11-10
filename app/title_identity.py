"""Check that a title is one folder name rather than a path."""


def validate_title_folder(folder):
    """Allow one folder name. Reject paths and anything that could escape the folder."""
    if (not isinstance(folder, str) or not folder.strip() or folder in (".", "..")
            or "/" in folder or chr(92) in folder
            or any(ord(char) < 32 or ord(char) == 127 for char in folder)):
        raise ValueError("Single safe title folder required")
    return folder
