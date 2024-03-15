# connect-quota 
Quota tool for OSG Connect systems.

# Features
## Filesystems
ZFS (wraps around zfs binary), XFS (wraps around quota binary), and Ceph (via xattrs) supported
## Mailgun Integration
Send mail to users and administrators via Mailgun's REST API
## User quota reporting
Write files with current quota information in a nice consolidated table for users

# Building
Install dependencies via pip (`requirements.txt`), or via yum (tested on EL7):
```bash
yum install python36-xattr python36-requests python36-tabulate
```
Note that the python3-devel package and the group 'Development Tools' should also be installed to install the packages via pip.

Build RPM
```bash
python3 setup.py bdist_rpm
```

# Contributing
Please install and run the 'black' formatter:
```bash
black connect-quota
```

Please also annotate functions with types where possible.
