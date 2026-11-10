"""Recognize housekeeping entries without treating them as media titles."""
import stat


def is_housekeeping(name, mode):
    return ((name == '.DS_Store' and stat.S_ISREG(mode))
            or (name == '.deletedByTMM' and stat.S_ISDIR(mode)))
