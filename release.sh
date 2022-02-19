#!/bin/sh
description=$1

if [ -z "$description" ]; then
  description="Releasing a new version"
fi

rm dist/*
init=$(cat serviceprovider/__init__.py)
oldVersion=$(echo "$init" | grep version | sed "s/__version__='//g" | sed "s/'//g")
version=$(echo "$oldVersion" | awk -F. -v OFS=. 'NF==1{print ++$NF}; NF>1{if(length($NF+1)>length($NF))$(NF-1)++;$NF=sprintf("%0*d", length($NF), ($NF+1)%(10^length($NF))); print}') &&
  echo "$init" | sed "s/$oldVersion/$version/g" >serviceprovider/__init__.py

python3.10 setup.py sdist
python3.10 -m twine upload dist/*
docker build -t python-ranger-daemon:"$version" . &&
docker tag python-ranger-daemon:"$version" tusharknaik/python-ranger-daemon:"$version" &&
docker push tusharknaik/python-ranger-daemon:"$version" &&

git tag -a "$version" -m "$description"
git push