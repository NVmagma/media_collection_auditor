"""Persistent share-writer opt-out review bytes; never apply host settings."""
import re

from app.sqlite_nfs_config_candidate import _disabled_candidate
from app.sqlite_disposable_nfs_config_plan import _prepare_disposable_config_plan


def _reviewed_cron(value):
    fields=value.split(b' ')
    if len(fields)!=5:return False
    for field,(lower,upper) in zip(fields,((0,59),(0,23),(1,31),(1,12),(0,7))):
        for item in field.split(b','):
            parts=item.split(b'/')
            if len(parts)>2:return False
            base=parts[0]
            if len(parts)==2:
                if (not parts[1].isdigit() or not 1<=int(parts[1])<=upper
                        or (base!=b'*' and b'-' not in base)):return False
            if base==b'*':continue
            bounds=base.split(b'-')
            if not 1<=len(bounds)<=2 or not all(n.isdigit() for n in bounds):return False
            values=[int(n) for n in bounds]
            if not lower<=values[0]<=values[-1]<=upper:return False
    return True


def disabled_boot_share_candidate(content):
    """Preserve all unrelated bytes, including storage auto-start preferences."""
    candidate=_disabled_candidate(content,key=b'shareSMBEnabled',label='SMB')
    candidate=_disabled_candidate(candidate,key=b'shareNFSEnabled',label='NFS')
    lines=candidate.splitlines(keepends=True)
    key=b'shareMoverSchedule'
    indices=[index for index,line in enumerate(lines)
             if re.match(rb'\s*(?:export\s+)?'+key+rb'\s*=',line)]
    if len(indices)!=1:raise ValueError('Exactly one explicit mover schedule required')
    index=indices[0]
    line=lines[index]
    ending=b'\r\n' if line.endswith(b'\r\n') else b'\n' if line.endswith(b'\n') else b''
    value=line[:-len(ending)] if ending else line
    # Official Disabled form submits an empty value. Never parse shell or
    # accept a command suffix as a schedule. Unknown forms need review.
    if value==key+b'=':
        replacement=value
    elif re.fullmatch(key+rb'="(?:[0-9*/,-]+(?: [0-9*/,-]+){4})?"',value):
        schedule=value[len(key)+2:-1]
        if schedule and not _reviewed_cron(schedule):
            raise ValueError('Mover schedule outside reviewed cron ranges')
        replacement=key+b'=""'
    else:
        raise ValueError('Canonical quoted mover schedule or explicit empty value required')
    lines[index]=replacement+ending
    return b''.join(lines)


def reviewed_boot_share_restore_candidate(*,original,disabled,current):
    if (disabled_boot_share_candidate(original)!=disabled
            or not isinstance(current,bytes) or current!=disabled):
        raise RuntimeError('Configuration changed; refuse restoration candidate')
    return original


def prepare_disposable_boot_share_config_plan(root):
    return _prepare_disposable_config_plan(root,source_name='share.cfg',
        plan_name='boot-share-plan',transform=disabled_boot_share_candidate,
        restore=reviewed_boot_share_restore_candidate,
        status='disposable_boot_share_candidates_prepared')
