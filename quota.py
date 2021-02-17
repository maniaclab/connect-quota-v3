#!/usr/bin/env python

import subprocess
import os
import sys
import pwd
import requests
import argparse
import logging
import xattr
from tabulate import tabulate


class Quota:
    """Return quota information in standard format for a variety of file systems"""
    def pp_user_form(self, quotas: list) -> str:
        """ Return quota information appropriate for printing to the user's shell upon login"""
        return

    def pp_short_report(self, quotas: list) -> str:
        headers = {
            "user": "User",
            "path": "Path",
            "blocks_pct": "Quota Used (%)",
            "blocks_used": "Blocks Used (GB)",
            "files_used": "Files",
        }
        report_quotas = self.filter_keys(quotas, headers.keys())  
        return tabulate(report_quotas, headers=headers)
        
    def filter_keys(self, quotas: list, filter_keys: list) -> list:
        filtered_quotas = []
        for q in quotas:
            new={key:value for (key,value) in q.items() if key in filter_keys}
            filtered_quotas.append(self.to_gb(new))
        return filtered_quotas

    def filter_full(self, quotas: list, key: str) -> list:
        newlist = []
        for q in quotas:
            try: 
                if q[key] > 100: # only works for blocks_pct and files_pct
                    newlist.append(q)
            except KeyError:
                logging.warning(f"Missing key in dict: {q}")
        return newlist
                

    def to_gb(self, quota: dict):
        convert_to_gb = ['blocks_used', 'blocks_soft', 'blocks_hard'] # keys that can be converted to gb
        for key in quota:
            if key in convert_to_gb:
                v = quota[key]
                quota[key] = round(v/1024**3,2)
        return quota

    def pp_full_report(self, quotas: list) -> str:
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
            "files_pct": "Files (%)"
        }
        return tabulate(quotas, headers=headers)

    def read_all_quotas(self, user: str, paths: list) -> list:
        quotas = []
        try:
            for p in paths:
                # Split along the colon delimeter
                s = p.split(":")
                path = s[0]
                fs = s[1]
                logging.info(f"Path is {path}, filesystem is {fs}")
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
            logging.error("Couldn't split path - did you provide it in path:filesystem format?")
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
            # This is not brittle at all!
            v = s.decode("utf-8").strip().split("\n")[-1]
            tokens = [int(x) for x in v.split()]
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
                quota["blocks_pct"] = round((quota["blocks_used"] / quota["blocks_soft"]) * 100, 2)
            else:
                quota["blocks_pct"] = None

            if quota["files_soft"] > 0:
                quota["files_pct"] = round((quota["files_used"] / quota["files_soft"]) * 100, 2)
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
            quota["blocks_pct"] = round((quota["blocks_used"] / quota["blocks_hard"]) * 100, 2)
        else:
            quota["blocks_pct"] = None

        if quota["files_hard"] > 0:
            quota["files_pct"] = round((quota["files_used"] / quota["files_hard"]) * 100, 2)
        else:
            quota["files_pct"] = None

        return quota

def get_all_users():
    users = []
    passwd = pwd.getpwall()
    for item in passwd:
        if item.pw_uid > 1000:
            users.append(item.pw_name)
    return users

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", nargs="+", help="user(s) for whom to get quota information (root only)")
    parser.add_argument("--all-users", action='store_true', help="Retrieve all users from /etc/passwd above UID 1000")
    parser.add_argument("--config", help="path to config file")
    parser.add_argument(
        "--log", help="standard python logging levels, e.g. INFO, ERROR, DEBUG"
    )
    parser.add_argument("--report", help="Filter quotas appropriately (single, short, full)")
    parser.add_argument("--fmt", help="Pass formatter option to Tabulate (e.g. plain, github, html, latex)")
    parser.add_argument("--only-full", action='store_true', help="Filter for only users who have gone beyond their quota")
    parser.add_argument(
        "--path",
        nargs="+",
        help="list of paths with colon delimited filesystem type, e.g. /home:xfs /public:ceph",
    )
    args = parser.parse_args()

    if args.path is None:
        logging.error(f"You must specify a path") 
        exit(1)

    if args.log is not None:
        loglevel = args.log
    else:
        loglevel = "ERROR"
    numeric_level = getattr(logging, loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError("Invalid log level: %s" % log)
    logging.basicConfig(level=numeric_level)

    if args.user is None and args.all_users is None:
        # Nothing specified, so just get a quota for ourself
        user = pwd.getpwuid(os.geteuid())[0]
    elif args.all_users is True:
        user = get_all_users()
    elif args.user is not None:
        user = args.user

    # this is merely informative - the user would get permission denied
    # if they try to run /bin/quota themselves.
    if os.geteuid() is not 0:
        if args.user is not None:
            logging.error("Only root can get quotas for another user")
            sys.exit(1)

    q = Quota()
    quota = []
    try:
        for u in user:
            quota.extend(q.read_all_quotas(u, args.path))
    except:
        raise
        sys.exit(1)

    if args.only_full is True:
        quota = q.filter_full(quota, 'blocks_pct')
        if len(quota) == 0:
            print("All users OK - nothing to report")
            exit(0)

    print(args.report)
    if "full" in args.report:
            results = q.pp_full_report(quota)
    else:
            results = q.pp_short_report(quota)
    print(results)
