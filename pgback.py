"""pgback.py: a simple Postgres-to-S3 backup script with GPG encryption"""

import logging
import os
import secrets
import smtplib
import subprocess
import tempfile
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import boto3
import botocore
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

LOGGER_TAG = "[pgback.py]"
TEMP_DIR_PREFIX = "pgback-"


# Read settings from env vars and .env
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
BACKUP_FILE_PREFIX = os.getenv("PGBACK_BACKUP_FILE_PREFIX")
DB_USER = os.getenv("PGBACK_DB_USER")
DB_PASSWORD = os.getenv("PGBACK_DB_PASSWORD")
DB_HOST = os.getenv("PGBACK_DB_HOST")
DB_PORT = int(os.getenv("PGBACK_DB_PORT"))
DB_NAME = os.getenv("PGBACK_DB_NAME")
GPG_KEY_ID = os.getenv("PGBACK_GPG_KEY_ID")
AWS_ACCESS_KEY_ID = os.getenv("PGBACK_AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("PGBACK_AWS_SECRET_ACCESS_KEY")
S3_BUCKET = os.getenv("PGBACK_S3_BUCKET")
S3_BUCKET_PATH = os.getenv("PGBACK_S3_BUCKET_PATH")
FAILURE_EMAIL_FROM = os.getenv("PGBACK_FAILURE_EMAIL_FROM")
FAILURE_EMAIL_TO = os.getenv("PGBACK_FAILURE_EMAIL_TO")
SMTP_HOST = os.getenv("PGBACK_SMTP_HOST")
SMTP_PORT = int(os.getenv("PGBACK_SMTP_PORT"))


def send_failure_email_notif():
    """Send a simple failure notification email."""

    msg = EmailMessage()
    msg["Subject"] = f"{LOGGER_TAG} Run failed"
    msg["From"] = FAILURE_EMAIL_FROM
    msg["To"] = FAILURE_EMAIL_TO
    utc_datetime = datetime.now(timezone.utc).isoformat()
    body = f"A backup run has failed as of {utc_datetime}."
    msg.set_content(body)

    try:
        smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        smtp.send_message(msg)
        smtp.quit()
    except OSError:  # smtplib (& socket) exceptions are subclasses of OSError
        logger.exception(
            "%s Error encountered while sending failure email.", LOGGER_TAG
        )


def main(tmpdirname):
    """Main routine."""

    #############
    # RUN PG_DUMP
    #############

    # Produce a datetime string of the form `2023-11-02T22-00-14Z`:
    utc_datetime = datetime.now(timezone.utc).isoformat()
    file_timestamp = utc_datetime[:19].replace(":", "-") + "Z"

    backup_file_name = (
        # Add a random string to the filename to ensure uniqueness
        f"{BACKUP_FILE_PREFIX}{file_timestamp}-{secrets.token_hex(4)}.pgdump"
    )
    backup_file_path = tmpdirname + "/" + backup_file_name
    try:
        subprocess.run(
            [
                "pg_dump",
                (
                    "--dbname=postgresql://"
                    f"{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
                ),
                "-Fc",
                "-f",
                backup_file_path,
            ],
            check=True,
        )
    except subprocess.SubprocessError:
        logger.exception("%s Error running pg_dump.", LOGGER_TAG)
        send_failure_email_notif()
        return

    ##################
    # ENCRYPT WITH GPG
    ##################

    encrypted_file_name = backup_file_name + ".gpg"
    encrypted_file_path = tmpdirname + "/" + encrypted_file_name
    try:
        subprocess.run(
            # Use `--trust-model always` to skip interactive
            # prompt in case the key is not trusted.
            [
                "gpg",
                "-r",
                GPG_KEY_ID,
                "--trust-model",
                "always",
                "-o",
                encrypted_file_path,
                "-e",
                backup_file_path,
            ],
            check=True,
        )
    except subprocess.SubprocessError:
        logger.exception("%s Error running gpg.", LOGGER_TAG)
        send_failure_email_notif()
        return

    ##############
    # UPLOAD TO S3
    ##############

    s3_client = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )
    try:
        s3_client.upload_file(
            encrypted_file_path, S3_BUCKET, S3_BUCKET_PATH + encrypted_file_name
        )
    except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError):
        logger.exception("%s Error running AWS S3 client.", LOGGER_TAG)
        send_failure_email_notif()


if __name__ == "__main__":
    logger.info("%s Starting run.", LOGGER_TAG)

    start_time = datetime.now()

    with tempfile.TemporaryDirectory(prefix=TEMP_DIR_PREFIX) as tmpdir:
        main(tmpdir)

    exec_seconds = (datetime.now() - start_time).seconds

    logger.info("%s Run complete.", LOGGER_TAG)
    logger.info("%s Execution time: %ss", LOGGER_TAG, exec_seconds)
