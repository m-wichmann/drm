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


## DVR converter

Additionaly this package contains a script to cut, crop and reencode DVR recordings with only a single reencoding. This isn't as polished, as the main script and should be used with care. It was only tested with one DVR and makes a couple of assumptions, that probably won't hold, with others.

If you are still eager to try it, install ffmpeg (probably already installed with Handbrake) and follow the steps below. The directory used in the commands has to contain the actual streams. The stream is expected to be split into multiple files, that are named aufnahme00.trp and so on.

1. Initializes the recording (concatenates the stream files)
        ./drm_dvr.py --init /some/dir/

2. Edit the cutlist to remove ads. You can just open the file /some/dir/drm_dvr.cfg by hand, since this command does not really work yet.
        ./drm_dvr.py --edit /some/dir/

3. Preview the recording and optionally add and configure the delogo and crop filters. Both use, more or less, the format specified by the ffmpeg filters.
        ./drm_dvr.py --preview /some/dir/

4. Encode the recording with the previously configured filters und cutlist. After it is done, the file /some/dir/out.mkv should be the final recording.
        ./drm_dvr.py --encode /some/dir/


## Links

* [Handbrake](https://handbrake.fr)
* [ffmpeg](https://ffmpeg.org/)
