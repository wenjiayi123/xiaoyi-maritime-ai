"""Tie the local simulator and native inference children to their Harness worker."""
import ctypes
from ctypes import wintypes as w
from contextlib import contextmanager
import subprocess

class BasicLimits(ctypes.Structure):
    _fields_=[("per_process",ctypes.c_int64),("per_job",ctypes.c_int64),("flags",w.DWORD),
              ("min_ws",ctypes.c_size_t),("max_ws",ctypes.c_size_t),("active",w.DWORD),("affinity",ctypes.c_size_t),
              ("priority",w.DWORD),("scheduling",w.DWORD)]
class ExtendedLimits(ctypes.Structure):
    _fields_=[("basic",BasicLimits),("io",ctypes.c_uint64*6),("memory",ctypes.c_size_t*4)]

@contextmanager
def process_tree(command,**options):
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    for name,args,result in [
        ("CreateJobObjectW",[w.LPVOID,w.LPCWSTR],w.HANDLE),("SetInformationJobObject",[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD],w.BOOL),
        ("AssignProcessToJobObject",[w.HANDLE,w.HANDLE],w.BOOL),("CloseHandle",[w.HANDLE],w.BOOL)]:
        fn=getattr(kernel,name);fn.argtypes=args;fn.restype=result
    job=kernel.CreateJobObjectW(None,None)
    if not job:raise ctypes.WinError(ctypes.get_last_error())
    child=None
    try:
        limits=ExtendedLimits();limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits)):raise ctypes.WinError(ctypes.get_last_error())
        child=subprocess.Popen(command,creationflags=subprocess.CREATE_NO_WINDOW|0x00000004,**options)
        # Attach the suspended interpreter launcher before it can spawn any descendants.
        if not kernel.AssignProcessToJobObject(job,int(child._handle)):raise ctypes.WinError(ctypes.get_last_error())
        resume=ctypes.WinDLL("ntdll").NtResumeProcess
        resume.argtypes=[w.HANDLE];resume.restype=ctypes.c_long
        if resume(int(child._handle))!=0:raise OSError("无法启动受控的编排子进程")
        yield child
    finally:
        kernel.CloseHandle(job)
        if child is not None:
            if child.poll() is None:child.kill()
            child.wait(timeout=10)
            if child.stdin and not child.stdin.closed:child.stdin.close()
