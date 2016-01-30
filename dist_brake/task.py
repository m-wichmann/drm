import tempfile
import os
from celery import Celery
from dist_brake.ftp import FTPClient, FTP_SERVER_PORT
from dist_brake.handbrake import Handbrake


import logging
logger = logging.getLogger('dist_hb')


app = Celery('tasks', backend='rpc://')

app.conf.update(CELERYD_PREFETCH_MULTIPLIER = 1)

server_ip = 'localhost'


def set_broker_url(user=None, password=None, ip=None, port=None):
    broker_url  = 'amqp://'
    broker_url += str(user) if user is not None else ''
    broker_url += (':' + str(password)) if password is not None else ''
    broker_url += '@' if user is not None else ''
    broker_url += str(ip) if ip is not None else ''
    broker_url += (':' + str(port)) if port is not None else ''

    app.conf.update(BROKER_URL = broker_url)


def start_worker(ip, user, password):
    server_ip = ip

    set_broker_url(user, password, ip)
    # NOTE: Only one thread at a time, since HB uses multiple processors
    app.worker_main(['worker', '--loglevel=INFO', '-c 1'])


@app.task
def handbrake_task(job):
    # TODO: check env

    temp_dir = tempfile.TemporaryDirectory()
    in_path = os.path.join(temp_dir.name, job.disc.remote_path)

    # get iso from master
    logger.info('Fetching file from server...')
    ftp_r = FTPClient(server_ip, FTP_SERVER_PORT, job.name, True)
    ftp_r.get_file(job.disc.remote_path, in_path)
    if not job.check_hash(in_path):
        raise Exception()
    del ftp_r

    files = []
    hb = Handbrake()
    titles = hb.scan_disc(in_path)
    titles = hb.filter_titles(titles,
                job.rip_config.len_range[0], job.rip_config.len_range[1],
                job.rip_config.a_lang, job.rip_config.s_lang)
    out_list = hb.encode_titles(job.hb_config, titles, in_path, temp_dir.name)
    for f in out_list:
        files.append({'name': f, 'hash': job._calc_hash(os.path.join(temp_dir.name, f))})

    # send files to master
    ftp_w = FTPClient(server_ip, FTP_SERVER_PORT, job.name, False)
    for f in files:
        ftp_w.put_file(os.path.join(temp_dir.name, f['name']), f['name'])
    del ftp_w

    return files
