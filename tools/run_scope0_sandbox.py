import argparse
import hashlib
import subprocess
from pathlib import Path


def run_scope0_sandbox(input_path: Path) -> subprocess.CompletedProcess[str]:
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    code = """
import _posixsubprocess, ctypes, errno, hashlib, os, pathlib, resource
import socket, sqlite3, subprocess, sys

expected = sys.argv[1]
allowed_input = f'/input/{expected}'
process_events = {
    'os.exec',
    'os.fork',
    'os.forkpty',
    'os.posix_spawn',
    'os.posix_spawnp',
    'os.spawn',
    'os.system',
    'subprocess.Popen',
}
filesystem_enumeration_events = {
    'os.chdir',
    'os.chroot',
    'os.fchdir',
    'os.listdir',
    'os.scandir',
}
write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
libc = ctypes.CDLL(None)
raw_syscall = libc.syscall
raw_syscall.restype = ctypes.c_long
errno_location = libc.__errno_location
errno_location.restype = ctypes.POINTER(ctypes.c_int)
errno_pointer = errno_location()

def policy_denial(event):
    raise PermissionError(f'E_SCOPE0_POLICY:{event}')

def block_fork_exec(*_args, **_kwargs):
    policy_denial('process.fork_exec')

def deny_forbidden_runtime(event, args):
    if event == 'open':
        target, mode, flags = args
        try:
            target = os.fsdecode(target)
        except TypeError:
            policy_denial(event)
        if target != allowed_input:
            policy_denial(event)
        if isinstance(mode, str) and any(marker in mode for marker in 'wax+'):
            policy_denial(event)
        if isinstance(flags, int) and flags & write_flags:
            policy_denial(event)
        return
    if event in filesystem_enumeration_events:
        policy_denial(event)
    if event in process_events or event.startswith('subprocess.'):
        policy_denial(event)
    if event.startswith('socket.'):
        policy_denial(event)
    if event == 'sqlite3.connect' or event.startswith('ctypes.'):
        policy_denial(event)

class SockFilter(ctypes.Structure):
    _fields_ = [
        ('code', ctypes.c_ushort),
        ('jt', ctypes.c_ubyte),
        ('jf', ctypes.c_ubyte),
        ('k', ctypes.c_uint32),
    ]

class SockFprog(ctypes.Structure):
    _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.POINTER(SockFilter))]

def install_seccomp():
    if os.uname().machine != 'x86_64':
        raise RuntimeError('E_SCOPE0_SECCOMP_UNSUPPORTED_ARCH')
    bpf_load_word_absolute = 0x20
    bpf_jump_equal_constant = 0x15
    bpf_return_constant = 0x06
    audit_arch_x86_64 = 0xC000003E
    seccomp_return_kill_process = 0x80000000
    seccomp_return_errno = 0x00050000 | errno.EPERM
    seccomp_return_allow = 0x7FFF0000
    denied_syscalls = (
        2,    # open
        41,   # socket
        42,   # connect
        56,   # clone
        57,   # fork
        58,   # vfork
        59,   # execve
        85,   # creat
        257,  # openat
        322,  # execveat
        435,  # clone3
        437,  # openat2
    )
    instructions = [
        SockFilter(bpf_load_word_absolute, 0, 0, 4),
        SockFilter(bpf_jump_equal_constant, 1, 0, audit_arch_x86_64),
        SockFilter(bpf_return_constant, 0, 0, seccomp_return_kill_process),
        SockFilter(bpf_load_word_absolute, 0, 0, 0),
    ]
    for syscall_number in denied_syscalls:
        instructions.extend(
            (
                SockFilter(bpf_jump_equal_constant, 0, 1, syscall_number),
                SockFilter(bpf_return_constant, 0, 0, seccomp_return_errno),
            )
        )
    instructions.append(SockFilter(bpf_return_constant, 0, 0, seccomp_return_allow))
    instruction_array = (SockFilter * len(instructions))(*instructions)
    program = SockFprog(len(instructions), instruction_array)
    libc.prctl.argtypes = (
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    )
    libc.prctl.restype = ctypes.c_int
    program_address = ctypes.cast(ctypes.pointer(program), ctypes.c_void_p).value
    if program_address is None or libc.prctl(38, 1, 0, 0, 0) != 0:
        raise RuntimeError('E_SCOPE0_SECCOMP_NO_NEW_PRIVS')
    if libc.prctl(22, 2, program_address, 0, 0) != 0:
        raise RuntimeError('E_SCOPE0_SECCOMP_FILTER_LOAD')

# CPython's private fork/exec primitive emits no audit event. Disable both
# reachable aliases, then make irreversible kernel controls reject bypasses.
subprocess._fork_exec = block_fork_exec
_posixsubprocess.fork_exec = block_fork_exec
resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))

content = pathlib.Path(allowed_input).read_bytes()
assert hashlib.sha256(content).hexdigest() == expected
install_seccomp()
sys.addaudithook(deny_forbidden_runtime)

def require_policy_denial(operation):
    try:
        operation()
    except PermissionError as exc:
        return str(exc).startswith('E_SCOPE0_POLICY:')
    except BaseException:
        return False
    return False

def fork():
    child = os.fork()
    if child == 0:
        os._exit(91)
    os.waitpid(child, 0)

def forkpty():
    child, _fd = os.forkpty()
    if child == 0:
        os._exit(92)
    os.waitpid(child, 0)

def posix_spawn():
    child = os.posix_spawn('/usr/bin/true', ['/usr/bin/true'], {})
    os.waitpid(child, 0)

def private_fork_exec():
    read_fd, write_fd = os.pipe()
    try:
        child = subprocess._fork_exec(
            ['/usr/bin/true'],
            (b'/usr/bin/true',),
            True,
            (write_fd,),
            None,
            None,
            -1,
            -1,
            -1,
            -1,
            -1,
            -1,
            read_fd,
            write_fd,
            True,
            False,
            -1,
            None,
            None,
            None,
            -1,
            None,
            False,
        )
        os.waitpid(child, 0)
    finally:
        os.close(read_fd)
        os.close(write_fd)

def require_kernel_denial(syscall_number, *args):
    errno_pointer.contents.value = 0
    result = raw_syscall(syscall_number, *args)
    if result < 0:
        return errno_pointer.contents.value == errno.EPERM
    if syscall_number == 57:
        if result == 0:
            os._exit(93)
        os.waitpid(result, 0)
    else:
        os.close(result)
    return False

checks = [
    require_policy_denial(operation)
    for operation in (
    lambda: pathlib.Path('/usr/bin/python3').read_bytes(),
    lambda: list(pathlib.Path('/usr').iterdir()),
    lambda: pathlib.Path('/etc/passwd').read_bytes(),
    lambda: sqlite3.connect('/blocked.sqlite'),
    lambda: socket.socket(),
    lambda: socket.create_connection(('127.0.0.1', 9), .1),
    lambda: subprocess.Popen(['/usr/bin/true']),
    lambda: subprocess.run(['/usr/bin/true'], check=True),
    lambda: os.system('/usr/bin/true'),
    posix_spawn,
    lambda: os.posix_spawnp('true', ['true'], {}),
    lambda: os.spawnve(os.P_WAIT, '/usr/bin/true', ['/usr/bin/true'], {}),
    lambda: os.execve('/usr/bin/true', ['/usr/bin/true'], {}),
    private_fork_exec,
    fork,
    forkpty,
    lambda: ctypes.CDLL(None),
    lambda: pathlib.Path('/operator').read_bytes(),
    lambda: pathlib.Path('/provider').read_bytes(),
    lambda: pathlib.Path('/raw').read_bytes(),
    )
]
assert all(checks), checks
assert require_kernel_denial(257, -100, b'/usr/bin/true', os.O_RDONLY, 0)
assert require_kernel_denial(41, socket.AF_INET, socket.SOCK_STREAM, 0)
assert require_kernel_denial(57)
print('SCOPE0_SANDBOX_OK')
"""
    argv = [
        "/usr/bin/bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--clearenv",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--dir",
        "/input",
        "--ro-bind",
        str(input_path),
        f"/input/{digest}",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "/usr/bin/python3",
        "-I",
        "-c",
        code,
        digest,
    ]
    return subprocess.run(  # noqa: S603 - fixed bwrap executable and arguments
        argv, text=True, capture_output=True
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    result = run_scope0_sandbox(args.input)
    if result.returncode != 0 or "SCOPE0_SANDBOX_OK" not in result.stdout:
        raise RuntimeError(f"E_SCOPE0_SANDBOX:{result.stderr.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
