import setuptools
import shutil
import os
from glob import glob
#from setuptools.config import read_configuration

BUILDDIR='build/'
if os.path.exists(BUILDDIR):
    shutil.rmtree(BUILDDIR)

setuptools.setup(
    name='connect-quota',
    version='1',
    author='Lincoln Bryant',
    author_email='lincolnb@uchicago.edu',
    description='CI Connect Quota Tool',
    url='https://github.com/maniaclab/connect-quota-v3',
    include_package_data=True,
    #package_dir={'': 'src'},
    #packages=[
    #    'connect-quota'
    #],
    scripts=[
        'scripts/connect-quota',
    ],
    install_requires=[
        'python36-xattr',
        'python36-requests',
        'python36-tabulate',
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)
#        ('/var/www/sysview/images', glob('static/images/*')),
