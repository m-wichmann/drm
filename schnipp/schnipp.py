#!/usr/bin/env python3

"""

Sources:
 * https://doc.qt.io/qt-5/qmlreference.html
 *
 *

"""

import sys
import argparse

from PyQt5.QtCore import QTranslator, QLocale, QObject, pyqtSlot, pyqtSignal
from PyQt5.QtQml import QQmlApplicationEngine
from PyQt5.QtGui import QIcon, QGuiApplication

import schnipp.detect_logo


class FileIO(QObject):
    """
    Provides functions to read and write files from QML GUI.

    Sources:
     - https://www.riverbankcomputing.com/static/Docs/PyQt5/signals_slots.html
     - https://www.riverbankcomputing.com/static/Docs/PyQt5/qml.html
    """
    def __init__(self):
        QObject.__init__(self)

    @pyqtSlot(str, str)
    def writeFile(self, filename, content):
        # TODO: Handle URL parameter better.
        with open(filename.replace('file://',''), 'w') as f:
            f.write(content)

    @pyqtSlot(str, result=str)
    def readFile(self, filename):
        try:
            with open(filename.replace('file://',''), 'r') as f:
                temp = f.read()
                return temp
        except FileNotFoundError as e:
            print(f'Could not open config file: {e}')
        return ''


class ImageProcessing(QObject):

    processingReady = pyqtSignal(int, int, int, int)

    def __init__(self):
        QObject.__init__(self)

    @pyqtSlot(int)
    def execute(self, no):
        file_list = ['./screengrab_{}.png'.format(i) for i in range(1, no+1)]
        result = schnipp.detect_logo.detect_logo(file_list)
        self.processingReady.emit(*result)


def run(path, style_argv=['--style', 'Fusion']):
    app = QGuiApplication(style_argv)
    app.setOrganizationName('Christian Wichmann')
    app.setApplicationName('Schnipp!')
    # start application
    engine = QQmlApplicationEngine()
    fileIO = FileIO()
    engine.rootContext().setContextProperty('FileIO', fileIO)
    imageProcessing = ImageProcessing()
    engine.rootContext().setContextProperty('ImageProcessing', imageProcessing)
    if path:
        engine.rootContext().setContextProperty('args', path)
    engine.load('schnipp/schnipp.qml')
    if not engine.rootObjects():
        sys.exit(-1)
    r = app.exec_()
    del engine
    sys.exit(r)
