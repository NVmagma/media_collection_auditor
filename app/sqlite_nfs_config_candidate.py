"""NFS preference candidates and exact restoration checks; never apply settings.

No service calls, shell sourcing, host installer or writer-exclusion permit.
"""
import re

LIMIT=1024*1024


def disabled_nfs_candidate(content):
    if not isinstance(content,bytes) or not 0<len(content)<=LIMIT or b'\0' in content:
        raise ValueError('Bounded text configuration required')
    content.decode('utf-8')
    lines=content.splitlines(keepends=True)
    indices=[index for index,line in enumerate(lines)
             if re.match(rb'\s*(?:export\s+)?shareNFSEnabled\s*=',line)]
    if len(indices)!=1:
        raise ValueError('Exactly one explicit NFS preference required')
    index=indices[0]
    line=lines[index]
    ending=b'\r\n' if line.endswith(b'\r\n') else b'\n' if line.endswith(b'\n') else b''
    value=line[:-len(ending)] if ending else line
    match=re.fullmatch(rb'shareNFSEnabled=("?)(yes|no)\1',value)
    if not match:
        raise ValueError('Unambiguous canonical NFS preference required')
    lines[index]=b'shareNFSEnabled='+match[1]+b'no'+match[1]+ending
    return b''.join(lines)


def reviewed_restore_candidate(*, original, disabled, current):
    """Return original bytes only for an exact unchanged disabled candidate.

    This is a review result, not atomic filesystem compare-and-swap or approval
    to restore services. Any later application needs its own held binding/CAS.
    """
    if disabled_nfs_candidate(original)!=disabled or not isinstance(current,bytes) or current!=disabled:
        raise RuntimeError('Configuration changed; refuse restoration candidate')
    return original
