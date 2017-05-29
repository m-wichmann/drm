import queue
import json
import os
import shutil
import threading
import time
import flask
from flask import Flask, Response, request, flash


HEARTBEAT_CHECK_PERIOD = 300         # in seconds


flask_app = Flask('drm')

job_queue = []
working_queue = []


def get_working_job_by_id(job_id):
    for job in working_queue:
        if (job.name == str(job_id)):
            return job
    return None


# TODO
#@flask_app.route('/version', methods=['GET'])
#def version():
#    return Response(DRM_VERSION, mimetype='application/json')


@flask_app.route('/job', methods=['GET'])
def get_job():
    # TODO: Return one job
    # TODO: What to do if no job available

    job = job_queue.pop()
    j = json.dumps(job, cls=ComplexEncoder)
    working_queue.append(job)

    return Response(j, mimetype='application/json')


@flask_app.route('/jobs/<uuid:job_id>', methods=['GET', 'POST'])
def handle_job(job_id):
    if request.method == 'POST':
        job = get_working_job_by_id(job_id)

        # Copy files
        for f in request.files:
            print('copy ', f)
            request.files[f].save(os.path.join(job.temp_path, f))
            job.files.append(os.path.join(job.temp_path, f))

        # read status
        if (request.form['state'] == 'DONE'):
            print('job done')
            job.teardown_env()
            shutil.move(job.disc.local_path, job.out_path)
            working_queue.remove(job)
            print('stuff moved')
        elif (request.form['state'] == 'WORKING'):
            pass
            # TODO: Heartbeat verarbeiten

        return ""
    else:
        job = get_working_job_by_id(job_id)
        (dir_path, file_name) = os.path.split(os.path.abspath(job.disc.local_path))
        return flask.send_from_directory(dir_path, file_name, as_attachment=True)


class ComplexEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj,'repr_json'):
            return obj.repr_json()
        else:
            return json.JSONEncoder.default(self, obj)


def heartbeat_thread():
    while 1:
        time.sleep(HEARTBEAT_CHECK_PERIOD)

        # TODO: handle heartbeat


def master_start_server(ip, port, _job_queue):
    global job_queue
    job_queue = _job_queue

    # add heartbeat thread
    t = threading.Thread(target=heartbeat_thread)
    t.start()

    flask_app.run(host=ip, port=port)
