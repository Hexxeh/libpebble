#!/bin/bash -e

#run as root

easy_install -U pyobjc-core
easy_install -U pyobjc
easy_install -U pyserial

git submodule update --init --recursive
cd lightblue-0.4
python setup.py install

echo lightblue successfully setup
