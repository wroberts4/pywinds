"""Convert command line arguments to python arguments for wind_functions.py"""
import argparse
import ast
import datetime
import logging
import numpy as np
import os
import sys
from glob import glob

import xarray

logger = logging.getLogger(__name__)


def area_to_string(area_dict, round_nums=None):
    """Rounds and converts area dict to string"""
    write_string = ''
    for key, val in area_dict.items():
        if val is not None and not isinstance(val, str) and isinstance(round_nums, int):
            val = np.round(val, round_nums).tolist()
        write_string = write_string + str(key) + ': ' + str(val) + '\n'
    return write_string[:-1]


def _nums_or_string(var):
    """Converts strings to number like python objects"""
    try:
        return ast.literal_eval('%s' % var)
    except (ValueError, SyntaxError):
        return var


class NullParser(argparse.ArgumentParser):
    """Used to nullify error output."""

    def error(self, message):
        return


class CustomParser(argparse.ArgumentParser):
    """Used to only add arguments that are needed."""

    def add_argument(self, *args, flag=None, force_include=False, **kwargs):
        if force_include or flag in args or set(args) & {'--help', '-h'}:
            super(CustomParser, self).add_argument(*args, **kwargs)


class MyFormatter(argparse.HelpFormatter):
    """Dynamically formats help message to be more informative."""

    def format_help(self):
        help_string = super(MyFormatter, self).format_help()
        formatter = ('{0} {0} {0} {0} {0}', '{0} {0} {0} {0}', '{0} {0} {0}', '{0} {0}', '{0}')
        for form in formatter:
            help_string = help_string.replace(form.format('UPPER_LEFT_EXTENT'), 'y x [units]')
            help_string = help_string.replace(form.format('RADIUS'), 'dy dx [units]')
            help_string = help_string.replace(form.format('AREA_EXTENT'), 'y_ll x_ll y_ur x_ur [units]')
            help_string = help_string.replace(form.format('CENTER'), 'y x [units]')
            help_string = help_string.replace(form.format('PIXEL_SIZE'), 'dy [dx] [units]')
            help_string = help_string.replace(form.format('EARTH_ELLIPSOID'), 'str [val [units]] [str val [units]]')
            help_string = help_string.replace(form.format('PROJECTION_ELLIPSOID'), 'str [val [units]] [str val [units]]')
        return help_string


class CustomAction(argparse.Action):
    """Dynamically finds correct number of nargs to use, then converts those numbers to correct python objects."""

    def __init__(self, option_strings, dest, narg_types=None, type=None, help=None):
        narg_types.sort(key=len)
        # If an error occurs or number of args are too small, use the bare minimum nargs.
        default_nargs = len(narg_types[0])
        # Setup narg_types so that larger lists take priority.
        narg_types = list(reversed(narg_types))
        # Setup parser to read all arguments after option.
        parser = NullParser()
        # Find the most amount of nargs possible.
        parser.add_argument(*option_strings, nargs='*')
        # Setup argv to remove help flags and let main parser handle help.
        argv = sys.argv[1:]
        while '-h' in argv:
            argv.remove('-h')
        while '--help' in argv:
            argv.remove('--help')
        known_args = parser.parse_known_args(argv)
        # Extract only arguments associated with option.
        if known_args is not None:
            args = getattr(known_args[0], dest)
            if args is None:
                super().__init__(option_strings, dest, nargs=default_nargs, help=help)
                return
            args = [type(arg) for arg in args]
        else:
            super().__init__(option_strings, dest, nargs=default_nargs, help=help)
            return
        # Try to match up narg_types with args from command line.
        for narg_type in narg_types:
            if len(narg_type) <= len(args):
                for i in range(len(narg_type)):
                    if not isinstance(args[i], narg_type[i]):
                        break
                # Every type matched up:
                else:
                    super().__init__(option_strings, dest, nargs=len(narg_type), help=help)
                    return
        super().__init__(option_strings, dest, nargs=default_nargs, help=help)

    def __call__(self, parser, args, values, option_string=None):
        values = [_nums_or_string(value) for value in values]
        if 'ellipsoid' in option_string or 'spheroid' in option_string:
            if len(values) == 1:
                values = values[0]
            else:
                if len(values) == 3:
                    values = {values[0]: xarray.DataArray(values[1], attrs={'units': values[2]})}
                elif len(values) == 5:
                    if isinstance(values[3], (int, float)):
                        values = {values[0]: values[1], values[2]: xarray.DataArray(values[3], attrs={'units': values[4]})}
                    else:
                        values = {values[0]: xarray.DataArray(values[1], attrs={'units': values[2]}), values[3]: values[4]}
                elif len(values) == 6:
                    values = {key: xarray.DataArray(val, attrs={'units': units}) for key, val, units in
                              zip(values[::3], values[-5::3], values[-4::3])}
                else:
                    values = {key: val for key, val in zip(values[::2], values[1::2])}
        else:
            units = None
            if isinstance(values[-1], str):
                units = values.pop(-1)
            if len(values) == 1:
                values = values[0]
            if units is not None:
                values = xarray.DataArray(values, attrs={'units': units})
        setattr(args, self.dest, values)


def _make_parser(flag_names, description):
    my_parser = CustomParser(description=description, formatter_class=MyFormatter)
    for flag in flag_names:
        my_parser.add_argument('old-lat', flag=flag, type=float, help='Latitude of starting location.')
        my_parser.add_argument('old-long', flag=flag, type=float, help='Longitude of starting locaion.')
        my_parser.add_argument('new-lat', flag=flag, type=float, help='Latitude of ending location')
        my_parser.add_argument('new-long', flag=flag, type=float, help='Longitude of ending location')
        my_parser.add_argument('distance', flag=flag, type=float, help='Distance to new location.')
        my_parser.add_argument('initial-bearing', flag=flag, type=float, help='Angle to new location.')
        my_parser.add_argument('forward-bearing', flag=flag, type=float, help='Angle to new location.')
        my_parser.add_argument('--inverse', flag=flag, action="store_true",
                               help='Find new location given a starting position, distance, and angle')

        my_parser.add_argument('lat', flag=flag, type=float, help='Latitude of position to transform into pixel.')
        my_parser.add_argument('long', flag=flag, type=float, help='Longitude of position to transform into pixel.')

        my_parser.add_argument('--lat-ts', flag=flag, type=float, metavar='float', help='projection latitude of true scale')
        my_parser.add_argument('--lat-0', flag=flag, type=float, metavar='float', help='projection latitude of origin')
        my_parser.add_argument('--long-0', flag=flag, type=float, metavar='float', help='projection central meridian')
        my_parser.add_argument('lat-ts', flag=flag, type=float, help='projection latitude of true scale')
        my_parser.add_argument('lat-0', flag=flag, type=float, help='projection latitude of origin')
        my_parser.add_argument('long-0', flag=flag, type=float, help='projection central meridian')
        my_parser.add_argument('delta-time', flag=flag, type=float,
                               help='Amount of time spent getting between ' + 'the two positions in minutes.')
        my_parser.add_argument('-p', '--print', '--no-save', flag=flag, action="store_true", dest='no_save',
                               help="print data to shell without saving")
        my_parser.add_argument('-s', '--save-directory', flag=flag, type=str, metavar='path-name',
                               help='directory to save to. Defaults to where script was ran')

        my_parser.add_argument('--from-lat-long', flag=flag, metavar='',
                               help='Switches to taking latitudes and longitudes as arguments. ' +
                                    'Use the args --from-lat-long -h for more information.')
        my_parser.add_argument('-j', '--j', flag=flag, type=int, metavar='int', help='row to run calculations on')
        my_parser.add_argument('-i', '--i', flag=flag, type=int, metavar='int', help='column to run calculations on')
        my_parser.add_argument('--center', flag=flag, action=CustomAction, type=_nums_or_string,
                               narg_types=[[(float, int), (float, int), str], [(float, int), (float, int)]],
                               help='projection y and x coordinate of the center of area. Default: lat long')
        my_parser.add_argument('--pixel-size', flag=flag, action=CustomAction, type=_nums_or_string,
                               narg_types=[[(float, int), (float, int), str], [(float, int), (float, int)],
                                           [(float, int), str], [(float, int)]],
                               help='projection size of pixels in the y and x direction.'
                                    'If pixels are square, i.e. dy = dx, then only one value needs to be entered')
        my_parser.add_argument('--displacement-data', flag=flag, type=_nums_or_string, metavar='filename',
                               help='filename or list containing displacements')
        my_parser.add_argument('--units', flag=flag, metavar='str',help='units that all provided arguments that take' +
                                                                   'units (except center) should be interpreted as')
        my_parser.add_argument('--upper-left-extent', flag=flag, action=CustomAction, type=_nums_or_string,
                               narg_types=[[(float, int), (float, int), str], [(float, int), (float, int)]],
                               help='projection y and x coordinates of the upper left corner of the upper left pixel')
        my_parser.add_argument('--radius', flag=flag, action=CustomAction, type=_nums_or_string,
                               narg_types=[[(float, int), (float, int), str], [(float, int), (float, int)]],
                               help='projection length from the center to the left/rightand top/bottom outer edges')
        my_parser.add_argument('--area-extent', flag=flag, action=CustomAction, type=_nums_or_string,
                               narg_types=[[(float, int) for i in range(4)] + [str], [(float, int) for i in range(4)]],
                               help='area extent in projection space: lower_left_y,'
                                    'lower_left_x, upper_right_y, upper_right_x')
        my_parser.add_argument('--shape', flag=flag, type=_nums_or_string, nargs=2, metavar=('height', 'width'),
                               help='number of pixels in the y and x direction')
        my_parser.add_argument('--projection', flag=flag, metavar='str', help='name of projection that the image is in')
        my_parser.add_argument('--earth-ellipsoid', '--earth-spheroid', flag=flag, action=CustomAction, type=_nums_or_string,
                               narg_types=[[str], [str, (float, int)], [str, (float, int), str],
                                           [str, (float, int), str, (float, int)],
                                           [str, (float, int), str, str, (float, int)],
                                           [str, (float, int), str, (float, int), str],
                                           [str, (float, int), str, str, (float, int), str]],
                               help='Ellipsoid of Earth. Coordinate system name or defined using a ' +
                                    'combination of a, b, e, es, f, and rf.')
        my_parser.add_argument('--projection-ellipsoid', '--projection-spheroid', flag=flag, action=CustomAction,
                               type=_nums_or_string,
                               narg_types=[[str], [str, (float, int)], [str, (float, int), str],
                                           [str, (float, int), str, (float, int)],
                                           [str, (float, int), str, str, (float, int)],
                                           [str, (float, int), str, (float, int), str],
                                           [str, (float, int), str, str, (float, int), str]],
                               help='Ellipsoid of projection. Coordinate system name or defined using a ' +
                                    'combination of a, b, e, es, f, and rf.')
    my_parser.add_argument('-v', '--verbose', action="count", default=0, force_include=True,
                           help='Each occurrence increases verbosity 1 level through ERROR-WARNING-INFO-DEBUG.')
    my_parser.add_argument('--precision', type=int, default=2, metavar='int', force_include=True,
                           help='Number of decimal places to round printed output to.')
    return my_parser


def _parse_args(flag_names, description):
    """Reads command line arguments and handles logic behind them."""
    parser = _make_parser(flag_names, description)
    commands = parser.parse_args()
    # Logging setup.
    levels = [logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG]
    logging_format = '[%(levelname)s: %(asctime)s : %(name)s] %(message)s'
    logging.basicConfig(level=levels[min(3, commands.verbose)], format=logging_format, datefmt='%Y-%m-%d %H:%M:%S')
    arg_names = [flag for flag in flag_names if flag[0] != '-']
    kwarg_names = [flag.lstrip('-').replace('-', '_') for flag in flag_names if flag[0] == '-']
    # Gets args and kwargs from command line data.
    args = [getattr(commands, arg) for arg in arg_names]
    kwargs = {'precision': commands.precision}
    for name in kwarg_names:
        val = getattr(commands, name, None)
        # Prevents variables not in function from being passed. ie no-save.
        if val is not None:
            kwargs[name] = val
    return args, kwargs


def run_script(func, flag_names, output_format, name):
    """Runs python function from wind_functions.py."""
    args, kwargs = _parse_args(flag_names, func.__doc__.splitlines()[0])
    precision = kwargs.pop('precision')
    if name == 'wind_info':
        kwargs['timestamp'] = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    displacement_data = kwargs.get('displacement_data')
    if name == 'wind_info_fll':
        kwargs['no_save'] = True
    if displacement_data is None and name in ['velocity', 'vu', 'wind_info', 'area', 'displacements']:
        displacement_data = os.path.join(os.getcwd(), '*.flo')
        kwargs['displacement_data'] = displacement_data
    if isinstance(displacement_data, str):
        files = glob(displacement_data)
        # If there are files, return after reading. Else let area fall through or error.
        if files:
            for file in files:
                kwargs['displacement_data'] = os.path.abspath(file)
                output = output_format(func(*args, **kwargs), precision, **kwargs)
                if output is not None:
                    print(output)
            return
        # File not found error will be raised from trying to find *.flo. Let area calculate as much as possible.
        elif name != 'area':
            func(*args, **kwargs)
        kwargs.pop('displacement_data')
    # Only happens with lat_long, area, position_to_pixel, or if non string is given to displacement-data.
    output = output_format(func(*args, **kwargs), precision, **kwargs)
    if output is not None:
        print(output)
