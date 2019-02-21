#!../../../anaconda3/envs/newpyre/bin/python3.6
from wrapper_utils import run_script
from wind_functions import wind_info
import sys
import numpy as np


def output_format(output, kwargs):
    if kwargs.get('save_data') is False:
        return np.round(output, 2).tolist()
    return ''


def main(argv):
    run_script(wind_info, argv, output_format, 'wind_info')


if __name__ == "__main__":
    main(sys.argv)
