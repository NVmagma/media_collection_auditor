"""Conservative, descriptor-held video/metadata inventory; never modifies files."""
import hashlib
import json
import os
from pathlib import Path
import stat
from time import monotonic
from app.filesystem_paths import _open_directory
from app.mount_identity import read_fd_mount_id

# Count zero-byte videos, stream pointers, disc images and incomplete downloads
# as media/unknown, never as disposable sidecars.
VIDEO_SUFFIXES=frozenset(('.mkv','.mp4','.m4v','.avi','.mov','.ts','.m2ts','.mts','.mpg','.mpeg',
    '.wmv','.iso','.webm','.ogv','.ogg','.flv','.3gp','.mxf','.vob','.ifo','.bup','.bdmv','.m2v','.strm'))
SIDECAR_SUFFIXES=frozenset(('.nfo','.jpg','.jpeg','.png','.webp','.srt','.ass','.ssa','.vtt','.sub','.idx'))
HOUSEKEEPING=frozenset(('.ds_store','thumbs.db','desktop.ini'))
MAX_ENTRIES=20000


def apple_double(directory,name,expected):
    """Validate bounded AppleDouble metadata headers (RFC 1740); never a data fork."""
    if not name.startswith('._') or not 26<=expected.st_size<=16*1024*1024:return False
    import struct
    child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    try:
        info=os.fstat(child)
        signature=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
        if signature(info)!=signature(expected):raise RuntimeError('Sidecar changed during read')
        header=os.read(child,26)
        if len(header)!=26:return False
        magic,version,_,count=struct.unpack('>II16sH',header)
        if magic!=0x00051607 or version!=0x00020000 or count>256:return False
        table=os.read(child,12*count)
        if len(table)!=12*count:return False
        ids=set();spans=[]
        for number in range(count):
            entry,offset,length=struct.unpack_from('>III',table,12*number)
            if entry in (0,1) or entry in ids or offset+length>info.st_size:return False
            if length:
                if offset<26+12*count or any(offset<end and start<offset+length for start,end in spans):return False
                spans.append((offset,offset+length))
            ids.add(entry)
        if signature(os.fstat(child))!=signature(expected):raise RuntimeError('Sidecar changed during read')
        return True
    finally:os.close(child)


def inspect_fd(fd):
    root=os.fstat(fd); mount=read_fd_mount_id(fd); started=monotonic(); rows=[]; unknown=False
    seen=set(); file_count=0; total_bytes=0
    for base,dirs,files,directory in os.fwalk('.',dir_fd=fd,follow_symlinks=False):
        info=os.fstat(directory)
        if len(Path(base).parts)>16 or read_fd_mount_id(directory)!=mount or (info.st_dev,info.st_ino) in seen:
            raise RuntimeError('Metadata inventory crosses a mount, alias or depth bound')
        seen.add((info.st_dev,info.st_ino))
        initial=(info.st_dev,info.st_ino,info.st_mtime_ns,info.st_ctime_ns)
        for name in sorted(dirs+files):
            if len(rows)>=MAX_ENTRIES or monotonic()-started>10: raise RuntimeError('Metadata inventory limit')
            item=os.stat(name,dir_fd=directory,follow_symlinks=False)
            if (item.st_dev!=root.st_dev or stat.S_ISLNK(item.st_mode)
                    or not (stat.S_ISREG(item.st_mode) or stat.S_ISDIR(item.st_mode))):
                raise RuntimeError('Unsupported metadata entry')
            if stat.S_ISREG(item.st_mode):
                resource_fork=apple_double(directory,name,item)
                # A validated resource-fork sidecar is metadata, not its .mkv data file.
                if not resource_fork and Path(name).suffix.lower() in VIDEO_SUFFIXES:
                    return {'status':'video_present','identity':[root.st_dev,root.st_ino]}
                known_sidecar=resource_fork or name.lower() in HOUSEKEEPING or Path(name).suffix.lower() in SIDECAR_SUFFIXES
                if known_sidecar and not resource_fork and item.st_nlink==1 and item.st_size<=16*1024*1024:
                    child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
                    try:
                        before=os.fstat(child)
                        signature=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
                        if signature(before)!=signature(item):raise RuntimeError('Sidecar changed during read')
                        header=os.read(child,16)
                        if signature(os.fstat(child))!=signature(item):raise RuntimeError('Sidecar changed during read')
                    finally:os.close(child)
                    if (header.startswith(b'\x1aE\xdf\xa3') or header[4:8]==b'ftyp'
                            or header[:4]==b'RIFF' and header[8:12]==b'AVI '
                            or header.startswith((b'\x00\x00\x01\xba',b'\x00\x00\x01\xb3'))):
                        return {'status':'video_present','identity':[root.st_dev,root.st_ino]}
                file_count+=1;total_bytes+=item.st_size
                if (item.st_nlink!=1 or item.st_size>16*1024*1024 or total_bytes>64*1024*1024
                        or not resource_fork and name.lower() not in HOUSEKEEPING and Path(name).suffix.lower() not in SIDECAR_SUFFIXES):
                    unknown=True
            rows.append([base,name,item.st_dev,item.st_ino,item.st_mode,item.st_size,item.st_mtime_ns,item.st_ctime_ns])
        end=os.fstat(directory)
        if initial!=(end.st_dev,end.st_ino,end.st_mtime_ns,end.st_ctime_ns):
            raise RuntimeError('Metadata changed during inventory')
    return {'status':'unknown_files' if unknown else 'metadata_only',
        'identity':[root.st_dev,root.st_ino],
        'fingerprint':hashlib.sha256(json.dumps([root.st_mtime_ns,sorted(rows)],ensure_ascii=True).encode()).hexdigest(),
        'files':file_count,'bytes':total_bytes}


def inspect_title(path):
    fd=_open_directory(path)
    try:
        parent=_open_directory(str(Path(path).parent))
        try:
            if read_fd_mount_id(parent)!=read_fd_mount_id(fd):raise RuntimeError('Title is a separate mount')
        finally:os.close(parent)
        return inspect_fd(fd)
    finally:os.close(fd)
