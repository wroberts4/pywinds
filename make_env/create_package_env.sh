#!/usr/bin/env bash

PARENTDIR="$( cd -P "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Remove names that are needed and may have been made in the past.
rm $PARENTDIR/new_pywinds.tar.gz 2> /dev/null
rm -r $PARENTDIR/pywinds 2> /dev/null

. ~/anaconda3/etc/profile.d/conda.sh
conda env update -n pywinds -f $PARENTDIR/../build_environment.yml
conda activate pywinds
pip install $PARENTDIR/..
conda-pack -o $PARENTDIR/new_pywinds.tar.gz --exclude conda-pack --exclude sphinx
mkdir $PARENTDIR/pywinds
mkdir $PARENTDIR/pywinds/env
tar -xzf $PARENTDIR/new_pywinds.tar.gz -C $PARENTDIR/pywinds/env
mv $PARENTDIR/pywinds/env/bin/*.sh $PARENTDIR/pywinds
mv $PARENTDIR/pywinds/env/bin/*.txt $PARENTDIR/pywinds
rm $PARENTDIR/new_pywinds.tar.gz

# Remove non-bash activate/deactivate scripts
rm -f $PARENTDIR/pywinds/env/etc/conda/activate.d/*.{fish,csh}
rm -f $PARENTDIR/pywinds/env/etc/conda/deactivate.d/*.{fish,csh}

tar -czf $PARENTDIR/new_pywinds.tar.gz pywinds
rm -r $PARENTDIR/pywinds
