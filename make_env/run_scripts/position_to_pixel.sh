#!/usr/bin/env bash

PARENTDIR="$( cd -P "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $PARENTDIR/env/bin/activate  2> /dev/null
python -W ignore<<EOF
import numpy as np
import sys

from os.path import abspath
from pywinds.wind_functions import position_to_pixel
from pywinds.wrapper_utils import run_script


def output_format(output, precision, **kwargs):
    return np.round(output, precision).tolist()


if __name__ == "__main__":
    sys.argv = [abspath("$0")] + "$*".split(' ')
    kwargs_names = ['--projection', '--area-extent', '--shape', '--center', '--pixel-size', '--upper-left-extent',
                    '--radius', '--projection-ellipsoid', '--units', '--displacement-data']
    args_names = ['lat-ts', 'lat-0', 'long-0', 'lat', 'long']
    run_script(position_to_pixel, kwargs_names + args_names, output_format, 'position_to_pixel')
EOF