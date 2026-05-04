#!/bin/bash

set -e

echo  "Git tag:     ${GIT_TAG}"
echo  "Git commit:  ${GIT_COMMIT}"

if [ -n "$GIT_TAG" ]
then
    # remove "v from vx.y.z in the tag"
    export VERSION="${GIT_TAG:1}"
elif [ -n "$GIT_COMMIT" ]
then
    export VERSION="${GIT_COMMIT:0:7}"
else
    echo "No GIT_TAG or GIT_COMMIT set. Defaulting to VERSION=dev"
    export VERSION="dev"
fi

# Update version.py
sed -i "s/__version__ = \"dev\"/__version__ = \"${VERSION}\"/g" src/version.py

# Update CloudFormation templates
for file in $(ls *.yaml);
do
    yq -i -e '.Metadata.Version.Description = strenv(VERSION)' $file
done
