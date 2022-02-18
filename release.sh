#!/bin/sh
rm dist/*
python3.10 setup.py sdist
python3.10 -m twine upload dist/*

version=$(cat version.txt)
version=$(echo "$version" | awk -F. -v OFS=. 'NF==1{print ++$NF}; NF>1{if(length($NF+1)>length($NF))$(NF-1)++;$NF=sprintf("%0*d", length($NF), ($NF+1)%(10^length($NF))); print}') &&
docker build -t python-ranger-daemon:"$version" . &&
docker tag python-ranger-daemon:"$version" tusharknaik/python-ranger-daemon:"$version" &&
docker push tusharknaik/python-ranger-daemon:"$version" &&
echo "$version" >version.txt
