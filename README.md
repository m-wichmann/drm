# drm - distributed russian mob

Distributed video transcoder based on HandBrake.


## Dependencies

Install all python requirements using pip:

    pip install -r requirements.txt

You also have to install Handbrake or rather HandBrakeCLI on all slaves.

    apt install handbrake-cli

To rip DVD images, the following tools are used: dvdbackup, genisoimage, eject.

To set properties of mkv files, mkvpropedit is used, which is part of mkvtoolnix.


## Workflow

1. Create the in and the out directory on the master, as well as a master
   configuration (encoding settings and directories).

2. Rip DVDs with the command:

        ./drm.py --rip master.cfg

3. Check the isos for errors by listing the titles with the following command.
   Make sure, the listed titles are as expected and plausible. This also detects
   "Special Needs" discs (e.g. needless duplicate titles etc.). In this case you
   can try one of the implemented workaround/fixes, or implement a new one.

        ./drm.py --list master.cfg

4. Start master with the command:

        ./drm.py --master master.cfg

5. Start each slave with the command:

        ./drm.py --slave slave.cfg

6. Sort and rename the resulting files as desired. To set the title of the file
   as a mkv property, you can use following command.

        ./drm.py --prop /path/to/files


## Links

* [Handbrake](http://handbrake.fr)
