#!/bin/sh
# Author: Tushar Naik
# I've used a lot of shortcuts to try to simulate the release of a new version from local
# Don't kill me if this screws up in unnecessary places

# Does the following:
#1. automatically incrementing version in __init__.py (required by setuptools for pypi distribution) and README.md
#2. setuptools and distribute on pypi
#3. create a docker image and push to docker repo tagged with the same version
#4. create a git tag
#5. finally push everything to remote

description=$1

if [ -z "$description" ]; then
  description="Releasing a new version"
fi

init=$(cat serviceprovider/__init__.py)
readme=$(cat README.md)
oldVersion=$(echo "$init" | grep version | sed "s/__version__='//g" | sed "s/'//g")
version=$(echo "$oldVersion" | awk -F. -v OFS=. 'NF==1{print ++$NF}; NF>1{if(length($NF+1)>length($NF))$(NF-1)++;$NF=sprintf("%0*d", length($NF), ($NF+1)%(10^length($NF))); print}') &&
  echo "$init" | sed "s/$oldVersion/$version/g" >serviceprovider/__init__.py &&
  echo "$readme" | sed "s/$oldVersion/$version/g" >README.md

rm dist/*
python3.10 setup.py sdist &&
  python3.10 -m twine upload dist/* &&
  docker build -t python-ranger-daemon:"$version" . &&
  docker tag python-ranger-daemon:"$version" tusharknaik/python-ranger-daemon:"$version" &&
  docker push tusharknaik/python-ranger-daemon:"$version" &&
  git add serviceprovider/__init__.py
git add README.md
git commit -m "Auto incrementing version to $version"
git tag -a "v$version" -m "$description"
git push
git push origin "v$version"
