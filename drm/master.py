import json
import os
import shutil
import threading
import time
import datetime
import logging

import flask
from flask import Flask, Response, request
import requests

import drm


logger = logging.getLogger('drm')


# TODO
HEARTBEAT_CHECK_PERIOD = 10         # in seconds
HEARTBEAT_TIMEOUT_PERIOD = 30       # in seconds


flask_app = Flask('drm')

out_path = '.'
job_queue = []
working_queue = {}                  # Format: {job: (host, timestamp), ...}


def get_working_job_by_id(job_id):
    for job in working_queue:
        if (job.name == str(job_id)):
            return job
    return None


@flask_app.route('/shutdown', methods=['POST'])
def shutdown():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return ""


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
            # TODO: outsource from job. Ok?
            for f in job.files:
                try:
                    shutil.move(f, out_path)
                except shutil.Error:
                    logger.error('Output file {filename} already exists. Skipping file...'.format(filename=f))
                    # TODO: what to do, if file already exists

            shutil.rmtree(job.temp_path)

            # TODO: this might take a _long_ time
            shutil.move(job.disc.local_path, out_path)
            del working_queue[job]
        elif (request.form['state'] == 'WORKING'):
            if working_queue[job][0] != host_address:
                logger.error('Job response from unknown host')
                del working_queue[job]
                job_queue.append(job)
                # TODO: response
                return ''

            working_queue[job] = (working_queue[job][0], timestamp)

        return ''
    else:
        (dir_path, file_name) = os.path.split(os.path.abspath(job.disc.local_path))
        return flask.send_from_directory(dir_path, file_name, as_attachment=True)


def heartbeat_thread():
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
            # TODO: Get ip/port from config
            url = 'http://{ip}:{port}/shutdown'.format(ip='127.0.0.1', port=5001)
            r = requests.post(url)
            return


def master_start_server(ip, port, _job_queue, _out_path):
    global job_queue
    job_queue = _job_queue

    global out_path
    out_path = _out_path

    # add heartbeat thread
    t = threading.Thread(target=heartbeat_thread)
    t.start()

    flask_app.run(host=ip, port=port, threaded=True)
