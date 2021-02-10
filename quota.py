#!/usr/bin/env python

import subprocess
import os
import sys
import pwd
import requests
import configparser
import argparse
import logging
import xattr


def read_quotas(user):
    quotas = []
    try:
        for path in config["PATHS"]:
            fs = config["PATHS"][path]
            logging.info(f"Path is {path}, filesystem is {fs}")
            q = {}  # initialization in case there's an error
            if "xfs" in fs:
                q = read_xfs_quota(user, path)
            elif "ceph" in fs:
                q = read_ceph_quota(user, path)
            else:
                logging.error(f"Filesystem type {fs} is not recognized")
            quotas.append(q)
    except KeyError as e:
        logging.error(f"Could not find key in config file: {e}")
    print(quotas)


def read_quota(user, fs, path):
    if "xfs" in fs:
        q = read_xfs_quota(user, path)
    elif "ceph" in fs:
        q = read_ceph_quota(user, path)
    else:
        logging.error(f"Filesystem type {fs} is not recognized")
    list.append(q)


def read_xfs_quota(user, path):
    q = xfs_quota_process(user, path)
    # keys:
    # blocks, bquota, blimit, bgrace, fils, fquota, flimit, fgrace
    if q is not {}:
        used = q["blocks_used"]
        lim = q["blocks_soft"]
        if lim > 0:
            pct = round((used / lim) * 100, 2)
            logging.info(
                f"XFS bytes for {path}/{user}: {used}/{lim} ({pct}%)"
            )

        used = q["files_used"]
        lim = q["files_soft"]
        if lim > 0:
            pct = round((used / lim) * 100, 2)
            logging.info(
                f"XFS files for {path}/{user}: {used}/{lim} ({pct}%)"
            )
    return q


def xfs_quota_process(user, path):
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
        tokens = v.split()
        quota = {
            "path": path,
            "filesystem": "xfs",
            "blocks_used": int(tokens[0]),  # blocks
            "blocks_soft": int(tokens[1]),  # quota
            "blocks_hard": int(tokens[2]),  # limit
            "blocks_days": int(tokens[3]),  # grace
            "files_used": int(tokens[4]),  # used
            "files_soft": int(tokens[5]),  # quota
            "files_hard": int(tokens[6]),  # limit
            "files_days": int(tokens[7]),  # grace
        }
        return quota
    except FileNotFoundError:
        logging.error(
            f"No such file or directory: {quotabin}. Is 'quota' installed?"
        )
        return {}


def read_ceph_quota(user, path):
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
        logging.error(
            f"Could not find key {key}. Is this a Ceph filesystem?"
        )
        return

    if max_bytes > 0:
        pct = round((rbytes / max_bytes) * 100, 2)
        logging.info(
            f"Ceph bytes for {path}/{user}: {rbytes}/{max_bytes} ({pct}%)"
        )
    if max_files > 0:
        pct = round((rfiles / max_files) * 100, 2)
        logging.info(
            f"Ceph files for {path}/{user}: {rfiles}/{max_files} ({pct}%)"
        )

    quota = {
        "path": path,
        "filesystem": "ceph",
        "blocks_used": rbytes,
        "blocks_soft": max_bytes,
        "blocks_hard": max_bytes,
        "blocks_days": -1,  # not used by ceph
        "files_used": rfiles,
        "files_soft": max_files,
        "files_hard": max_files,
        "files_days": -1,
    }
    return quota


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--user", help="user for whom to get quota information"
    )
    parser.add_argument("--config", help="path to config file")
    parser.add_argument("--log", help="INFO, ERROR, DEBUG")
    args = parser.parse_args()
    config = configparser.ConfigParser()

    if args.log is not None:
        loglevel = args.log
    else:
        loglevel = "ERROR"
    numeric_level = getattr(logging, loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError("Invalid log level: %s" % log)
    logging.basicConfig(level=numeric_level)

    if args.config is not None:
        cfg = args.config
    else:
        cfg = "config.ini"
    config.read(cfg)

    if args.user is not None:
        user = args.user
    else:
        user = pwd.getpwuid(os.geteuid())[0]

    if os.geteuid() is not 0:
        if args.user is not None:
            # this is merely informative - the user would get permission denied
            # if they try to run /bin/quota themselves.
            logging.error("Only root can get quotas for another user")
            sys.exit(1)

    read_quotas(user)
