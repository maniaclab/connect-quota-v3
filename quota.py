#!/usr/bin/env python

import subprocess
import os
import socket
import sys
import pwd
import requests
import argparse
import logging
import xattr
import time
from tabulate import tabulate
from pathlib import Path


class Report:
    def notify_users(self, quota: list):
        # Ensure we filter the dictionary for only full users. We never want to
        # send a quote report if the user isn't full.
        quota = self.filter_full(quota, "blocks_pct")
        for q in quota:
            report = self.short_report([q], tablefmt="html")
            body = "<p> Your user account on your OSG Connect login node ("
            body += socket.gethostname()
            body += ") has gone over your data quota on one or more file systems: <br>"
            body += report
            body += "<br>Please remove any unneeded files as soon as possible and reply to this email (or contact us at support@opensciencegrid.org) if you need any additional help or have questions/comments."
            body += (
                "<br><br>Thanks, <br>Research Facilitation Team <br>Open Science Grid"
            )

            if self.check_last_mailed(q["user"]):
                user = q["user"]
                email = Path("/home/" + user + "/.forward")
                if email.exists():
                    self.mail(
                        "lincolnb@uchicago.edu",  # replaceme with user's email
                        "Your Open Science Grid account is over quota",
                        body,
                    )
                else:
                    logging.error(
                        f"Forward file does not exist! User {user} cannot be notified!"
                    )

    def check_last_mailed(self, user: str):
        path = Path("/home/" + user + "/.quota")
        if not path.exists():
            logging.debug("Path doesn't exist. will create.")
            path.touch(mode=0o600)
        last_modified = path.stat().st_mtime
        now = time.time()
        week = 604800  # 1 week in seconds
        delta = now - last_modified
        if delta >= week:
            logging.debug(
                f"File was last touched ({now} - {last_modified}) {delta} seconds ago"
            )
            logging.info(f"User {user} notified - updating quota file!")
            path.touch(mode=0o600)
            return True
        else:
            return False

    def mail(self, to, subject, body):
        mailgun_url = os.environ.get("MAILGUN_URL")
        if mailgun_url is None:
            mailgun_url = "https://api.mailgun.net/v3/api.ci-connect.net/messages"
            logging.warning("No MAILGUN_URL found in environment, using default")
        mailgun_api_key = os.environ.get("MAILGUN_API_KEY")
        if mailgun_api_key is None:
            logging.error(
                "No API key present - did you set MAILGUN_API_KEY in your environment?"
            )
        r = requests.post(
            mailgun_url,
            auth=("api", mailgun_api_key),
            data={
                "subject": subject,
                "from": "<noreply@api.ci-connect.net>",
                "to": to,
                "html": body,
            },
        )
        logging.info(f"Response code is {r.status_code}")
        return r.status_code

    def filter_keys(self, quotas: list, filter_keys: list) -> list:
        filtered_quotas = []
        for q in quotas:
            new = {key: value for (key, value) in q.items() if key in filter_keys}
            filtered_quotas.append(self.to_gb(new))
        return filtered_quotas

    def filter_full(self, quotas: list, key: str) -> list:
        newlist = []
        for q in quotas:
            try:
                if q[key] > 100:  # only works for blocks_pct and files_pct
                    newlist.append(q)
            except KeyError:
                logging.warning(f"Missing key in dict: {q}")
        return newlist

    def to_gb(self, quota: dict):
        convert_to_gb = [
            "blocks_used",
            "blocks_soft",
            "blocks_hard",
        ]  # keys that can be converted to gb
        for key in quota:
            if key in convert_to_gb:
                v = quota[key]
                quota[key] = round(v / 1024 ** 3, 2)
        return quota

    def short_report(self, quotas: list, tablefmt="simple") -> str:
        headers = {
            "user": "User",
            "path": "Path",
            "blocks_pct": "Quota Used (%)",
            "blocks_used": "Blocks Used (GB)",
            "files_used": "Total Files (#)",
        }
        report_quotas = self.filter_keys(quotas, headers.keys())
        return tabulate(report_quotas, headers=headers, tablefmt=tablefmt)

    def full_report(self, quotas: list, tablefmt="simple") -> str:
        headers = {
            "user": "User",
            "path": "Path",
            "filesystem": "Fs",
            "blocks_used": "Used (Bytes)",
            "blocks_soft": "Soft (Bytes)",
            "blocks_hard": "Hard (Bytes)",
            "blocks_days": "Grace (Days)",
            "files_used": "Files (N)",
            "files_soft": "Soft (N)",
            "files_hard": "Hard (N)",
            "files_days": "Grace (Days)",
            "blocks_pct": "Bytes (%)",
            "files_pct": "Files (%)",
        }
        return tabulate(quotas, headers=headers, tablefmt=tablefmt)


class Quota:
    """Return quota information in standard format for a variety of file systems"""

    def get_all_users(self):
        users = []
        passwd = pwd.getpwall()
        for item in passwd:
            if item.pw_uid > 1000:
                users.append(item.pw_name)
        return users

    def read_all_quotas(self, user: str, paths: list) -> list:
        quotas = []
        try:
            for p in paths:
                # Split along the colon delimeter
                s = p.split(":")
                path = s[0]
                fs = s[1]
                q = {}  # initialization in case there's an error
                if "xfs" in fs:
                    q = self.read_xfs_quota(user, path)
                elif "ceph" in fs:
                    q = self.read_ceph_quota(user, path)
                else:
                    logging.error(f"Filesystem type {fs} is not recognized")
                if q:
                    quotas.append(q)
        except IndexError as e:
            logging.error(
                "Couldn't split path - did you provide it in path:filesystem format?"
            )
            raise IndexError
        return quotas

    def read_xfs_quota(self, user: str, path: str) -> dict:
        quota = {}
        try:
            quotabin = "/bin/quota"
            # /bin/quota is awful. You cannot specifiy a filesystem AND a username.
            # Has to be one or the other.
            # TODO: Validate against multiple filesystems - probably will fail
            s = subprocess.run(
                [quotabin, "-w", "--hide-device", "-p", "-u", user],
                stdout=subprocess.PIPE,
            ).stdout
            # This is not brittle at all! :)
            # First decode UTF-8 string, then strip spaces, then delete
            # asterisks (XFS uses these to report full filesystems), split
            # on newlines, and take the last value.
            stripped = s.decode("utf-8").strip().replace("*", "").split("\n")[-1]
            tokens = [int(x) for x in stripped.split()]
            quota = {
                "user": user,
                "path": path,
                "filesystem": "xfs",
                "blocks_used": tokens[0] * 1024,  # blocks
                "blocks_soft": tokens[1] * 1024,  # quota
                "blocks_hard": tokens[2] * 1024,  # limit
                "blocks_days": tokens[3],  # grace
                "files_used": tokens[4],  # files
                "files_soft": tokens[5],  # quota
                "files_hard": tokens[6],  # limit
                "files_days": tokens[7],  # grace
            }
            # calculate percentages if possible
            if quota["blocks_soft"] > 0:
                quota["blocks_pct"] = round(
                    (quota["blocks_used"] / quota["blocks_soft"]) * 100, 2
                )
            else:
                quota["blocks_pct"] = None

            if quota["files_soft"] > 0:
                quota["files_pct"] = round(
                    (quota["files_used"] / quota["files_soft"]) * 100, 2
                )
            else:
                quota["files_pct"] = None

            return quota

        except FileNotFoundError:
            logging.error(
                f"No such file or directory: {quotabin}. Is 'quota' installed?"
            )
            return {}
        except ValueError as e:
            logging.warning(f"An error occured processing quota for {user}: {e}")
            return {}

    def read_ceph_quota(self, user: str, path: str) -> dict:
        quota = {}
        try:
            os.stat(path + "/" + user)
        except FileNotFoundError:
            logging.error(f"Could not find {path}/{user}")
            return
        x = xattr.xattr(f"{path}/{user}")

        try:
            key = "ceph.quota.max_bytes"
            max_bytes = int(x[key])

            key = "ceph.dir.rbytes"
            rbytes = int(x[key])

            key = "ceph.quota.max_files"
            max_files = int(x[key])

            key = "ceph.dir.rfiles"
            rfiles = int(x[key])
        except KeyError:
            logging.error(f"Could not find key {key}. Is this a Ceph filesystem?")
            return quota

        quota = {
            "user": user,
            "path": path,
            "filesystem": "ceph",
            "blocks_used": rbytes,
            "blocks_soft": max_bytes,
            "blocks_hard": max_bytes,
            "blocks_days": None,
            "files_used": rfiles,
            "files_soft": max_files,
            "files_hard": max_files,
            "files_days": None,
        }
        # calculate percentages if possible
        if quota["blocks_hard"] > 0:
            quota["blocks_pct"] = round(
                (quota["blocks_used"] / quota["blocks_hard"]) * 100, 2
            )
        else:
            quota["blocks_pct"] = None

        if quota["files_hard"] > 0:
            quota["files_pct"] = round(
                (quota["files_used"] / quota["files_hard"]) * 100, 2
            )
        else:
            quota["files_pct"] = None

        return quota


if __name__ == "__main__":
    q = Quota()
    r = Report()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--user",
        nargs="+",
        help="user(s) for whom to get quota information (root only)",
    )
    parser.add_argument(
        "--all-users",
        action="store_true",
        help="Retrieve all users from /etc/passwd above UID 1000",
    )
    parser.add_argument("--config", help="path to config file")
    parser.add_argument(
        "--log", help="standard python logging levels, e.g. INFO, ERROR, DEBUG"
    )
    parser.add_argument(
        "--report", help="Filter quotas appropriately (single, short, full)"
    )
    parser.add_argument(
        "--fmt",
        default="simple",
        help="Pass formatter option to Tabulate (e.g. plain, github, html, latex)",
    )
    parser.add_argument(
        "--only-full",
        action="store_true",
        help="Filter for only users who have gone beyond their quota",
    )
    parser.add_argument(
        "--path",
        nargs="+",
        help="list of paths with colon delimited filesystem type, e.g. /home:xfs /public:ceph",
    )
    parser.add_argument("--mailto", help="Email address for recipient")
    parser.add_argument(
        "--notify-users",
        action="store_true",
        help="Write an email to the user over quota",
    )
    args = parser.parse_args()

    if args.path is None:
        logging.error(f"You must specify a path, e.g. /home:xfs")
        exit(1)

    if args.log is not None:
        loglevel = args.log
    else:
        loglevel = "ERROR"
    numeric_level = getattr(logging, loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError("Invalid log level: %s" % log)
    logging.basicConfig(level=numeric_level)

    if args.all_users is True:
        user = q.get_all_users()
        logging.debug("Getting information for all users")
    elif args.user is None:
        # Nothing specified, so just get a quota for ourself
        user = [pwd.getpwuid(os.geteuid())[0]]
        logging.debug("Getting information for current user")
    elif args.user is not None:
        user = args.user
        logging.debug("Getting information for particular user")

    # this is merely informative - the user would get permission denied
    # if they try to run /bin/quota themselves.
    if os.geteuid() is not 0:
        if args.user is not None:
            logging.error("Only root can get quotas for another user")
            sys.exit(1)

    quota = []
    try:
        for u in user:
            quota.extend(q.read_all_quotas(u, args.path))
    except:
        raise
        sys.exit(1)

    if args.only_full is True:
        quota = r.filter_full(quota, "blocks_pct")
        if len(quota) == 0:
            print("All users OK - nothing to report")
            exit(0)

    if args.report == "full":
        results = r.full_report(quota, args.fmt)
    else:
        results = r.short_report(quota, args.fmt)

    if args.mailto is not None:
        mailgun_url = os.environ.get("MAILGUN_URL")
        if mailgun_url is None:
            mailgun_url = "https://api.mailgun.net/v3/api.ci-connect.net/messages"
            logging.warning("No MAILGUN_URL found in environment, using default")
        mailgun_api_key = os.environ.get("MAILGUN_API_KEY")
        if mailgun_api_key is None:
            logging.error(
                "No API key present - did you set MAILGUN_API_KEY in your environment?"
            )
            exit(1)
        subject = "Quota report for " + socket.gethostname()
        r = requests.post(
            mailgun_url,
            auth=("api", mailgun_api_key),
            data={
                "subject": subject,
                "from": "<noreply@api.ci-connect.net>",
                "to": args.mailto,
                "html": results,
            },
        )
        logging.info(f"Response code is {r.status_code}")
    elif args.notify_users is True:
        r.notify_users(quota)

    else:
        print(results)
