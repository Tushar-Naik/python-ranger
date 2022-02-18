#!/bin/sh
rm dist/*
python3.10 setup.py sdist
python3.10 -m twine upload dist/*