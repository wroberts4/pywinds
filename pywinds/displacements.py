#!/usr/bin/env python
from pywinds.wrapper_utils import run_script
from pywinds.wind_functions import displacements
import sys
import numpy as np
import warnings


def output_format(output, kwargs):
    return np.round(output, 2).tolist()


def main(argv):
    run_script(displacements, argv, output_format, 'displacements')


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=UserWarning, module='pyproj')
    main(sys.argv)
