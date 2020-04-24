
# Schnipp

Schnipp is a simple GUI to clip letterbox bars and mark broadcaster logos in video files.

## Build

To update the localisation and create translation files:

    lupdate schnipp.qml -ts i18n/de_DE.ts
    linguist i18n/de_DE.ts
    lrelease i18n/*.ts

To build the standalone C++ programm:

    qmake -makefile
    make

To start the program as Python script:

    python3 schnipp.py

## Requirements

To run Schnipp under Ubuntu 19.10 you need to install the necessary packages:

    apt install python3-pyqt5 python3-pyqt5.qtquick qml-module-qtquick-controls2 qml-module-qtquick-extras qml-module-qtmultimedia qml-module-qt-labs-settings qml-module-qt-labs-folderlistmodel libqt5multimedia5-plugins

## Third Party

* Icon from [Tango icon](http://tango-project.org/) set under Public Domain.
