import subprocess
import codecs


DVDBACKUP_BIN = 'dvdbackup'
GENISOIMAGE_BIN = 'genisoimage'
EJECT_BIN = 'eject'
MKVPROPEDIT = 'mkvpropedit'


def popen_wrapper(cmd, timeout=None):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    retval = None
    stdout = ""
    stderr = ""

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()

    retval = proc.returncode

    stdout = codecs.decode(stdout, 'utf-8', 'replace')
    stderr = codecs.decode(stderr, 'utf-8', 'replace')

    return (retval, stdout, stderr)


def dvdbackup(output_dir, title_name):
    cmd = [DVDBACKUP_BIN,
           '-M',                    # "mirror"; Backup whole DVD
           '-i', '/dev/dvd',        # input device
           '-o', output_dir,        # output directory
           '-n', title_name]        # Title name
    (retval, stdout, stderr) = popen_wrapper(cmd)
    return retval == 0


def dvdbackup_check():
    try:
        (retval, stdout, stderr) = popen_wrapper([DVDBACKUP_BIN, '--version'])
        return retval == 0
    except FileNotFoundError:
        return False


def genisoimage(out_path, temp_path):
    cmd = [GENISOIMAGE_BIN,
           '-dvd-video',
           '-o', out_path,
           temp_path]
    (retval, stdout, stderr) = popen_wrapper(cmd)
    return retval == 0


def genisoimage_check():
    try:
        (retval, stdout, stderr) = popen_wrapper([GENISOIMAGE_BIN, '--version'])
        return retval == 0
    except FileNotFoundError:
        return False


def eject():
    (retval, stdout, stderr) = popen_wrapper([EJECT_BIN])
    return retval == 0


def eject_check():
    try:
        (retval, stdout, stderr) = popen_wrapper([EJECT_BIN, '--version'])
        return retval == 0
    except FileNotFoundError:
        return False


def mkvpropedit(path, title):
    cmd = [MKVPROPEDIT,
           path,
           '--edit', 'info',
           '--set', 'title={title}'.format(title=title)]
    (retval, stdout, stderr) = popen_wrapper(cmd)


def mkvpropedit_check():
    try:
        (retval, stdout, stderr) = popen_wrapper([MKVPROPEDIT, '--version'])
        return retval == 0
    except FileNotFoundError:
        return False
