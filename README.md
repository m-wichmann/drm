# drm - distributed russian mob

Distributed video transcoder based on HandBrake and Celery.


## Dependencies

Install all python requirements using pip:

    pip install -r requirements.txt

You also have to install Handbrake or rather HandBrakeCLI on all slaves.

    apt install handbrake-cli

The master needs to install a broker for celery. Currently only RabbitMQ is
supported and tested. You should configure a user for drm in RabbitMQ.

    apt install rabbitmq-server

To rip DVD images, the following tools are used: dvdbackup, genisoimage, eject.

To set properties of mkv files, mkvpropedit is used, which is part of mkvtoolnix.


## Deployment

Check if host configuration is ok: Host name set and entry for 127.0.0.1 in
hosts file.

Set up user and vhost in RabbitMQ:

    sudo rabbitmqctl add_user myuser mypassword
    sudo rabbitmqctl add_vhost myvhost
    sudo rabbitmqctl set_permissions -p myvhost myuser ".*" ".*" ".*"

Create slave config (ip address of the master and the user/password for rabbitmq
e.g. "myuser"/"mypassword")


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

* [Handbrake](handbrake.fr)
* [Celery](celeryproject.org)
* [RabbitMW](rabbitmq.com)
