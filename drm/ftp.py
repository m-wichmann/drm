from threading import Thread
from ftplib import FTP
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import ThreadedFTPServer


import logging
logger = logging.getLogger('drm')


FTP_SERVER_PORT = 50021


ftp_server = None


class FTPServerWrapper(object):
    class TestHandler(FTPHandler):
        def on_incomplete_file_received(self, file):
            print('on_incomplete_file_received({})'.format(file))
            # TODO: delete incomplete file, mark job as unfinished

    class FTPServerRunner(Thread):
        def __init__(self, server):
            self.server = server
            super(FTPServerWrapper.FTPServerRunner, self).__init__()

        def run(self):
            self.server.serve_forever()

    def __init__(self, port=('', FTP_SERVER_PORT)):
        self.auth = DummyAuthorizer()
        self.handler = FTPServerWrapper.TestHandler
        self.handler.authorizer = self.auth
        self.server = ThreadedFTPServer(port, self.handler)

        self.port = port

        self.users = []
        self.t = FTPServerWrapper.FTPServerRunner(self.server)
        self.t.start()

    def __del__(self):
        self.server.close_all()
        self.server.close()
        del self.server

    def add_user(self, name, r_dir, w_dir):
        logging.info('adding ftp user {}'.format(name))
        self.users.append(name)
        self.auth.add_user('r-' + str(name), name, r_dir, perm='rl')
        self.auth.add_user('w-' + str(name), name, w_dir, perm='wl')

    def rem_user(self, name):
        logging.info('removing ftp user {}'.format(name))
        try:
            self.users.remove(name)
            self.auth.remove_user('r-' + str(name))
            self.auth.remove_user('w-' + str(name))
        except ValueError:
            pass


def ftp_get_server():
    global ftp_server
    if ftp_server is None:
        ftp_server = FTPServerWrapper()
    return ftp_server


class FTPClient(object):
    def __init__(self, host, port, name, r_w):
        self.ftp = FTP()
        self.ftp.connect(host=host, port=port)
        if r_w:
            self.ftp.login(user='r-' + name, passwd=name)
        else:
            self.ftp.login(user='w-' + name, passwd=name)

    def get_file(self, source, dest):
        logging.info('copying {} to {}'.format(source, dest))
        with open(dest, 'wb') as fd:
            def callback(data):
                fd.write(data)
            self.ftp.retrbinary('RETR {ftp_file}'.format(ftp_file=source), callback)

    def put_file(self, source, dest):
        logging.info('copying {} to {}'.format(source, dest))
        with open(source, 'rb') as fd:
            self.ftp.storbinary('STOR {ftp_file}'.format(ftp_file=dest), fd)
