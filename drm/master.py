import threading
import datetime
import logging
import shutil
import json
import time
import os

from flask import Flask, Response, request, render_template, send_from_directory
import requests

import drm
from drm.data import HandbrakeConfig, RipConfig


logger = logging.getLogger('drm')

HEARTBEAT_CHECK_PERIOD = 10         # in seconds
HEARTBEAT_TIMEOUT_PERIOD = 30       # in seconds

flask_app = Flask('drm')

hb_config = HandbrakeConfig()
rip_config = RipConfig()
fixes = []
out_path = '.'
job_queue = []
working_queue = {}                  # Format: {job: (host, timestamp), ...}
done_queue = []


def format_len_range_config(value):
    m = value % 60
    h = value // 60
    if h == 0:
        out = '{m}m'.format(m=m)
    elif m == 0:
        out = '{h}h'.format(h=h, m=m)
    else:
        out = '{h}h{m:02}m'.format(h=h, m=m)
    return out


flask_app.jinja_env.filters['format_len_range_config'] = format_len_range_config


def get_working_job_by_id(job_id):
    for job in working_queue:
        if (job.name == str(job_id)):
            return job
    return None


@flask_app.route('/', methods=['GET'])
def status():
    generated_time = datetime.datetime.now().isoformat()
    return render_template('status.html', waiting=job_queue, working=working_queue, done=done_queue, generated_time=generated_time, hb_config=hb_config, rip_config=rip_config, fixes=fixes)


@flask_app.route('/shutdown', methods=['POST'])
def shutdown():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return ''


@flask_app.route('/version', methods=['GET'])
def version():
    return Response(json.dumps(drm.__version__), mimetype='application/json')


@flask_app.route('/jobs/', methods=['GET'])
def get_job():
    host_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    timestamp = datetime.datetime.now()

    try:
        job = job_queue.pop()
        job_desc = json.dumps({'name': job.name, 'rip_config': job.rip_config.dump_data(), 'hb_config': job.hb_config.dump_data(), 'fixes': [fix.dump_data() for fix in job.fixes]})
        working_queue[job] = (host_address, timestamp)
        logger.info('Job %s assigned to %s', job, host_address)
    except IndexError:
        # No more jobs available
        job_desc = json.dumps(None)

    return Response(job_desc, mimetype='application/json')


@flask_app.route('/jobs/<uuid:job_id>', methods=['GET', 'POST'])
def handle_job(job_id):
    job = get_working_job_by_id(job_id)

    if job is None:
        logger.warning('Job %s not found!', str(job_id))
        return ''

    host_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    timestamp = datetime.datetime.now()

    if request.method == 'POST':
        # Copy files
        for f in request.files:
            logger.info('Copying %s from %s [%s]', f, host_address, job_id)
            request.files[f].save(os.path.join(job.temp_path, f))
            job.files.append(os.path.join(job.temp_path, f))

        # read status
        if (request.form['state'] == 'DONE'):
            for f in job.files:
                try:
                    shutil.move(f, out_path)
                except shutil.Error:
                    logger.error('Output file {filename} already exists. Skipping file...'.format(filename=f))
            shutil.rmtree(job.temp_path)
            shutil.move(job.disc.local_path, out_path)

            del working_queue[job]
            done_queue.append(job)
        elif (request.form['state'] == 'WORKING'):
            if working_queue[job][0] != host_address:
                logger.error('Job response from unknown host')
                del working_queue[job]
                job_queue.append(job)
                return ''

            working_queue[job] = (working_queue[job][0], timestamp)

        return ''
    else:
        (dir_path, file_name) = os.path.split(os.path.abspath(job.disc.local_path))
        return send_from_directory(dir_path, file_name, as_attachment=True)


def heartbeat_thread(ip, port):
    while True:
        time.sleep(HEARTBEAT_CHECK_PERIOD)

        timestamp = datetime.datetime.now() - datetime.timedelta(seconds=HEARTBEAT_TIMEOUT_PERIOD)

        job_timeout_list = []

        for job in working_queue:
            if working_queue[job][1] < timestamp:
                logger.error('Job %s timed out', job)
                job_timeout_list.append(job)

        for job in job_timeout_list:
            del working_queue[job]
            job_queue.append(job)

        if len(working_queue) == 0 and len(job_queue) == 0:
            logger.info('No jobs left. Shutting down server...')
            url = 'http://{ip}:{port}/shutdown'.format(ip=ip, port=port)
            r = requests.post(url)
            return


def master_start_server(ip, port, _job_queue, _out_path):
    global job_queue
    job_queue = _job_queue
    global out_path
    out_path = _out_path

    if len(_job_queue) > 0:
        global rip_config
        rip_config = _job_queue[0].rip_config
        global hb_config
        hb_config = _job_queue[0].hb_config
        global fixes
        fixes = _job_queue[0].fixes

    # add heartbeat thread
    t = threading.Thread(target=heartbeat_thread, args=(ip, port))
    t.start()

    flask_app.run(host=ip, port=port, threaded=True)
