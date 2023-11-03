# pgback.py: a simple Postgres-to-S3 backup script with GPG encryption

This is a database backup tool suitable for small deployments for which continuous backup (for point-in-time restoration) is not required. It employs PostgreSQL’s standard `pg_dump` utility with GnuPG for public-key encryption and Amazon S3 for storage. S3-compatible services (such as DigitalOcean Spaces) may also work, though it might require some tweaks in the script. Basic email notifications are also sent upon failures.

This script is intended for Linux servers, and has been tested specifically with Ubuntu 22.04.

You are free to pronounce the name as “piggyback pie”. 😉

## Requirements and installation

The script assumes that `pg_dump` and `gpg` are available in the `PATH` of the user with which the script will be run.

For the failure emails, the script currently only works with unauthenticated SMTP, because it’s written for a server with a `localhost:25` SMTP relay setup.

The following instructions describe a `systemd.timer` setup for scheduling the script’s execution, although of course you can also use `cron`.

1. Clone or copy this repository to a suitable location.
2. Import or create a GPG (public) key to the user’s keyring to be used for encrypting the backup files. Please refer to GnuPG documentation (or the internet) for this, if you do not know how to.
3. Create a Python virtual environment, e.g. with `venv`, and populate with dependencies from the `requirements-lock.txt` file. For example:

        cd /home/myuser/pgback
        python3 -m venv venv
        . venv/bin/activate
        pip install -r requirements-lock.txt

4. Configure the script by creating and filling out a `.env` file, placing it in the same directory as `pgback.py`; see the `.env.dist` template for details on the required settings. For additional security of the database and S3 credentials, you will probably want to store them in a separate environment file accessible only by the root user, as described below.
5. Set up the `systemd` service and timer.
    - Store the sensitive settings in a root-owned environment file. For example:

            sudo mkdir /etc/myproject
            sudo cd /etc/myproject
            sudo touch pgback.env
            sudo chmod 600 pgback.env
            sudo nano pgback.env

    - Create the service file, e.g. `sudo nano /etc/systemd/system/pgback.service` and input the following (changing the filenames, directories, and user/group as appropriate):

            [Unit]
            Description=Postgres-to-S3 encrypted backup
            After=network.target

            [Service]
            Type=oneshot
            User=myuser
            Group=mygroup
            WorkingDirectory=/home/myuser/pgback
            ExecStart=/home/myuser/pgback/venv/bin/python pgback.py
            EnvironmentFile=/etc/myproject/pgback.env

    - Create the timer file, e.g. `sudo nano /etc/systemd/system/pgback.timer` and input the following (this `OnCalendar` setting runs the script twice a day, at 06:00 and 18:00, every day):

            [Unit]
            Description=Postgres-to-S3 encrypted backup

            [Timer]
            OnCalendar=*-*-* 06,18:00:00

            [Install]
            WantedBy=timers.target

    - Enable and start the timer: `sudo systemctl enable --now pgback.timer`
    - Test the installation by running the script with `sudo systemctl start pgback.service` and then checking the logs with `journalctl -u pgback`

## Security considerations

It is recommended that a dedicated AWS user is created for S3 access, assigned only the `PutObject` permission.

The GPG encryption command in the script uses `--trust-model always`; this means that you should make sure that you trust the GPG key used for encrypting the backup (or just generate a dedicated key pair for this backup setup).

The installation guide above describes a way to protect sensitive settings (DB password and AWS keys) by storing them in a root-owned file. Note that newer versions of `systemd` [recommend a more sophisticated setup for credentials management](https://systemd.io/CREDENTIALS/).

## Backing up multiple databases

You can use the same script file for backing up multiple databases by setting up multiple `systemd` service-timer pairs, each using a distinct `EnvironmentFile`. Just make sure to put database-specific settings in each `systemd` environment file; these variables should override settings found in the `pgback/.env` file.
