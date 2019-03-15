import ntpath
import os
import h5py
import numpy as np
from pyproj import Geod, Proj
from pyresample.geometry import AreaDefinition, DynamicAreaDefinition
from pyresample.utils import proj4_str_to_dict
import xarray

"""Find wind info"""


# TODO: UPDATE DOCS
def save_data(displacement_filename, data_list, txt_shape=None, mode='a'):
    if isinstance(displacement_filename, str):
        head, tail = ntpath.split(displacement_filename)
        extension = tail or ntpath.basename(head)
    else:
        extension = 'list'
    directory = os.path.join(os.getcwd(), extension + '_output')
    netcdf4_path = os.path.join(directory, 'wind_info.nc')
    try:
        os.mkdir(directory)
    except OSError:
        pass

    dataset_dict = {}
    encoding = {}
    for data in data_list:
        dataset_dict[data.name] = data
        encoding[data.name] = {'dtype': np.float32}
        # Text file handling
        text_path = os.path.join(directory, data.name + '.txt')
        if None not in data.data:
            data = data.data
            if np.size(data) == 1:
                data = np.ravel(data)
            np.savetxt(text_path, data.reshape(txt_shape), fmt='%.2f', delimiter=',')
        else:
            write_string = ''
            for key, val in data.attrs.items():
                if data.attrs[key] is None:
                    data.attrs[key] = 'None'
                write_string = write_string + str(key) + ': ' + str(val) + '\n'
            with open(text_path, 'w') as file:
                file.write(write_string)
    xarray.Dataset(dataset_dict, attrs={'Conventions': 'CF-1.7'}).to_netcdf(netcdf4_path, mode=mode, format='NETCDF4',
                                                                            encoding=encoding)


def _extrapolate_j_i(j, i, shape):
    """Extrapolates j and i to be the entire image if they are not provided."""
    if np.size(i) != 1 or np.size(j) != 1 or i is None and j is not None or j is None and i is not None:
        raise ValueError('i and j must both be integers or None but were {0} {1} and {2} {3} '
                         'respectively'.format(i, type(i), j, type(j)))
    if i is None:
        j = [x for x in range(0, shape[1]) for y in range(0, shape[0])]
        i = [y for x in range(0, shape[1]) for y in range(0, shape[0])]
    else:
        if j >= shape[0]:
            raise IndexError('index {0} is out of bounds for vertical axis with size {1}'.format(j, shape[0]))
        if i >= shape[1]:
            raise IndexError('index {0} is out of bounds for horizontal axis with size {1}'.format(i, shape[1]))
        i = _to_int(i, ValueError('i must be a positive integer'))
        j = _to_int(j, ValueError('j must be a positive integer'))
        if i < 0:
            raise ValueError('i must be a positive integer')
        if j < 0:
            raise ValueError('j must be a positive integer')
    # returns (i, j)
    return np.array(j), np.array(i)


def _reverse_params(params):
    """Reverses the order of parameters (y/x-form is given, but most packages need x/y-form."""
    reversed_params = []
    for param in params:
        units = None
        if isinstance(param, xarray.DataArray):
            units = param.attrs.get('units', None)
            param = param.data.tolist()
        if np.shape(param) != ():
            param = list(reversed(param))
        if units is not None:
            return xarray.DataArray(param, attrs={'units': units})
        reversed_params.append(param)
    return reversed_params


def _to_int(num, error):
    """Converts objects to integers."""
    if num is None:
        return None
    try:
        if int(num) != num:
            raise TypeError
    except (TypeError, ValueError):
        raise error
    return int(num)


def _pixel_to_pos(area_definition, j, i):
    """Converts (j, i) pixels to a position on the Earth in projection space."""
    u_l_pixel = area_definition.pixel_upper_left
    # (x, y) in projection space.
    position = u_l_pixel[0] + area_definition.pixel_size_x * i, u_l_pixel[1] - area_definition.pixel_size_y * j
    return position


def _delta_longitude(new_long, old_long):
    """Calculates the change in longitude on the Earth."""
    delta_long = new_long - old_long
    if abs(delta_long) > 180.0:
        if delta_long > 0.0:
            return delta_long - 360.0
        else:
            return delta_long + 360.0
    return delta_long


def _lat_long_dist(lat, earth_geod):
    """Calculates the distance between latitudes and longitudes given a latitude."""
    if earth_geod is None:
        earth_geod = Geod(ellps='WGS84')
    elif isinstance(earth_geod, str):
        earth_geod = Geod(ellps=earth_geod)
    else:
        raise ValueError(
            'earth_geod must be a string or Geod type, but instead was {0} {1}'.format(earth_geod, type(earth_geod)))
    geod_info = proj4_str_to_dict(earth_geod.initstring)
    e2 = (2 - 1 * geod_info['f']) * geod_info['f']
    lat = np.pi / 180 * lat
    # Credit: https://gis.stackexchange.com/questions/75528/understanding-terms-in-length-of-degree-formula/75535#75535
    # 2 * pi * r / 360 = distance per 1 degree.
    lat_dist = 2 * np.pi * geod_info['a'] * (1 - e2) / (1 - e2 * np.sin(lat) ** 2) ** 1.5 / 360
    long_dist = 2 * np.pi * geod_info['a'] / (1 - e2 * np.sin(lat) ** 2) ** .5 * np.cos(lat) / 360
    return lat_dist, long_dist


def _not_none(args):
    for arg in args:
        if arg is not None:
            return True
    return False


# TODO: USE CREATE_AREA WHEN RELEASES: from pyresample import create_area_def
def _create_area(lat_ts, lat_0, long_0, projection='stere', area_extent=None, shape=None, center=None, pixel_size=None,
                 image_geod=None, displacement_data=None, no_save=True):
    """Creates area from given information."""
    save_data(displacement_data, [xarray.DataArray(None, name='polar_stereographic')], mode='w')
    if not isinstance(projection, str):
        raise ValueError('projection must be a string, but instead was {0} {1}'.format(projection, type(projection)))
    # Center is given in (lat, long) order, but create_area_def needs it in (long, lat) order.
    if area_extent is not None:
        area_extent_ll, area_extent_ur = area_extent[0:2], area_extent[2:4]
    else:
        area_extent_ll, area_extent_ur = None, None
    center, pixel_size, area_extent_ll, area_extent_ur = _reverse_params(
        [center, pixel_size, area_extent_ll, area_extent_ur])
    if area_extent is not None:
        # Needs order [ll_x, ll_y, ur_x, ur_y].
        area_extent = area_extent_ll + area_extent_ur
    # if center is not None and not isinstance(center, xarray.DataArray):
    #     center = xarray.DataArray(center, attrs={'units': 'degrees'})
    if image_geod is None:
        image_geod = Geod(ellps='WGS84')
    elif isinstance(image_geod, str):
        image_geod = Geod(ellps=image_geod)
    else:
        raise ValueError(
            'image_geod must be a string or Geod type, but instead was {0} {1}'.format(image_geod, type(image_geod)))
    proj_dict = proj4_str_to_dict(
        '+lat_ts={0} +lat_0={1} +lon_0={2} +proj={3} {4}'.format(lat_ts, lat_0, long_0, projection,
                                                                 image_geod.initstring))
    # Temporary fix to allow sphere until proj4 6.0.0 releases.
    if proj_dict['f'] == 0:
        proj_dict.pop('f', None)
        proj_dict['R'] = proj_dict.pop('a', None)
    # proj_dict['b'] = proj_dict['a'] * (1 - proj_dict.pop('f'))
    # TODO: REMOVE THIS WHEN PYRESAMPLE MAKES NEW RELEASE.
    if center is None:
        center = (long_0, lat_0)
    if area_extent is None and center is not None and pixel_size is not None and shape is not None:
        center = Proj(proj_dict)(*center, error_check=True)
        area_extent = [center[0] - pixel_size * shape[1] / 2, center[1] - pixel_size * shape[0] / 2,
                       center[0] + pixel_size * shape[1] / 2, center[1] + pixel_size * shape[0] / 2]
    if shape is None and pixel_size is not None and area_extent is not None:
        shape = (area_extent[3] - area_extent[1]) / pixel_size, (area_extent[2] - area_extent[0]) / pixel_size
    if area_extent is not None and shape is not None:
        area_definition = AreaDefinition('pywinds', 'pywinds', '', proj_dict, shape[1], shape[0], area_extent)
    elif shape is not None:
        area_definition = DynamicAreaDefinition(proj_dict=proj_dict, x_size=shape[1], y_size=shape[0])
    elif area_extent is not None:
        area_definition = DynamicAreaDefinition(proj_dict=proj_dict, area_extent=area_extent)
    else:
        raise ValueError('Not enough information provided to create an area definition')
    # area_definition = create_area_def('pywinds', proj_dict, area_extent=area_extent, shape=shape,
    #                         resolution=pixel_size,
    #                        center=center,  units=units)
    p = Proj(proj_dict)
    a = proj_dict.get('a')
    f = proj_dict.get('f')
    if a is None or f is None:
        a = proj_dict['R']
        f = 0.0
    if abs(f) > 0.0:
        i_f = 1 / f
    else:
        i_f = 0
    area_extent = area_definition.area_extent
    if area_extent is not None:
        center = ((area_extent[1] + area_extent[3]) / 2, (area_extent[0] + area_extent[2]) / 2)
        center = _reverse_params([p(center[1], center[0], inverse=True)])[0]
        area_extent = _reverse_params([p(area_extent[0], area_extent[1], inverse=True)])[0] + \
                      _reverse_params([p(area_extent[2], area_extent[3], inverse=True)])[0]
    else:
        center = None
        area_extent = None
    if area_definition.y_size is None or area_definition.x_size is None:
        shape = None
    else:
        shape = [area_definition.y_size, area_definition.x_size]
    try:
        pixel_size = [area_definition.pixel_size_y, area_definition.pixel_size_x]
    except AttributeError:
        pixel_size = None
    if no_save is False:
        if displacement_data is None:
            raise ValueError('Cannot save data without displacement_data')
        up_longitude = p(0, 100, inverse=True)[0]
        if up_longitude == 180:
            up_longitude = -180.0
        b = a * (1 - f)
        e = (1 - b ** 2 / a ** 2) ** .5
        # http://earth-info.nga.mil/GandG/coordsys/polar_stereographic/Polar_Stereo_phi1_from_k0_memo.pdf
        k90 = ((1 + e) ** (1 + e) * (1 - e) ** (1 - e)) ** .5
        phi = np.pi * lat_ts / 180
        k0 = (1 + np.sin(phi)) / 2 * k90 / ((1 + e * np.sin(phi)) ** (1 + e) * (1 - e * np.sin(phi)) ** (1 - e)) ** .5
        save_data(displacement_data, [xarray.DataArray(None, name='polar_stereographic',
                                                       attrs={'straight_vertical_longitude_from_pole': up_longitude,
                                                              'latitude_of_projection_origin': float(lat_0),
                                                              'scale_factor_at_projection_origin': k0,
                                                              'standard_parallel': float(lat_ts),
                                                              'resolution_at_standard_parallel':
                                                                  np.ravel(pixel_size)[0],
                                                              'false_easting': 0.0, 'false_northing': 0.0,
                                                              'semi_major_axis': a, 'semi_minor_axis': b,
                                                              'inverse_flattening': i_f})])
    return {'projection': projection, 'lat_0': lat_0, 'long_0': long_0, 'equatorial radius': a, 'eccentricity': f,
            'shape': shape, 'area_extent': area_extent, 'pixel_size': pixel_size, 'center': center}, area_definition


def _find_displacements(displacement_data=None, j=None, i=None, shape=None, no_save=True):
    """Retrieves pixel-displacements from a file or list."""
    if isinstance(displacement_data, str):
        # Displacement: even index, odd index. Note: (0, 0) is in the top left, i=horizontal and j=vertical.
        displacement = np.array(np.fromfile(displacement_data, dtype=np.float32)[3:], dtype=np.float64)
        j_displacement = displacement[1::2]
        i_displacement = displacement[0::2]
        if shape is None:
            shape = np.fromfile(displacement_data, dtype=int)[1:3]
            if (shape[0] is 0 or shape[1] != np.size(j_displacement) / shape[0] or
                    shape[1] != np.size(i_displacement) / shape[0]):
                shape = None
    elif displacement_data is not None:
        if len(np.shape(displacement_data)) != 2 and len(np.shape(displacement_data)) != 3 or \
                np.shape(displacement_data)[0] != 2:
            raise ValueError(
                'displacement_data should have shape (2, y * x) or (2, y, x), but instead has shape {0}'.format(
                    np.shape(displacement_data)))
        if len(np.shape(displacement_data)) != 2:
            displacement_data = np.reshape(displacement_data, (2, int(np.size(displacement_data) / 2)))
        j_displacement = np.array(displacement_data[0], dtype=np.float64)
        i_displacement = np.array(displacement_data[1], dtype=np.float64)
    else:
        return shape, 0.0, 0.0
    if shape is None:
        shape = [np.size(i_displacement) ** .5, np.size(j_displacement) ** .5]
        error = 'Shape was not provided and shape found from file was not comprised of integers: ' \
                '{0} pixels made a shape of {1}'.format(np.size(j_displacement) + np.size(i_displacement),
                                                        tuple([2] + shape))
        shape = (_to_int(shape[0], ValueError(error)), _to_int(shape[1], ValueError(error)))
    if shape[0] is 0 or shape[1] != np.size(j_displacement) / shape[0]:
        raise ValueError('Could not reshape displacement data of size {0} to shape {1}'.format(
            np.size(j_displacement), shape))
    if shape[0] is 0 or shape[1] != np.size(i_displacement) / shape[0]:
        raise ValueError('Could not reshape displacement data of size {0} to shape {1}'.format(
            np.size(i_displacement), shape))
    if j is not None or i is not None:
        j, i = _extrapolate_j_i(j, i, shape)
        j_displacement, i_displacement = j_displacement[j * shape[0] + i], i_displacement[j * shape[0] + i]

    dims = None
    if np.size(j_displacement) != 1:
        dims = ['y', 'x']
    if no_save is False:
        save_data(displacement_data,
              (xarray.DataArray(_reshape(j_displacement, shape), name='j_displacement', dims=dims,
                                attrs={'standard_name': 'divergence_of_wind',
                                       'description': 'vertical pixel displacement at each pixel',
                                       'grid_mapping': 'polar_stereographic'}),
               xarray.DataArray(_reshape(i_displacement, shape), name='i_displacement', dims=dims,
                                attrs={'standard_name': 'divergence_of_wind',
                                       'description': 'horizontal pixel displacement at each pixel',
                                       'grid_mapping': 'polar_stereographic'})))
    return shape, j_displacement, i_displacement


def _reshape(array, shape):
    if np.size(array) == 1:
        return array
    return np.reshape(array, shape)


def _compute_lat_long(lat_ts, lat_0, long_0, displacement_data=None, projection='stere', j=None, i=None,
                      area_extent=None, shape=None, center=None, pixel_size=None, image_geod=None, no_save=True):
    """Computes the latitude and longitude given an area and (j, i) values."""
    if not isinstance(lat_0, (int, float)) or not isinstance(long_0, (int, float)):
        raise ValueError(
            'lat_0 and long_0 must be ints or floats, but instead were ' + '{0} {1} and {2} {3} respectively'.format(
                lat_0, type(lat_0), long_0, type(long_0)))
    shape, j_displacement, i_displacement, area_definition = _find_displacements_and_area(lat_ts=lat_ts, lat_0=lat_0,
                                                                                          long_0=long_0,
                                                                                          displacement_data=displacement_data,
                                                                                          projection=projection, j=j,
                                                                                          i=i, area_extent=area_extent,
                                                                                          shape=shape,
                                                                                          center=center,
                                                                                          pixel_size=pixel_size,
                                                                                          image_geod=image_geod,
                                                                                          no_save=no_save)[:4]
    # Function that handles projection to lat/long transformation.
    p = Proj(area_definition.proj_dict, errcheck=True, preserve_units=True)
    # If i and j are None, make them cover the entire image.
    j_new, i_new = _extrapolate_j_i(j, i, shape)
    # Returns (lat, long) in degrees.
    new_long, new_lat = p(*_pixel_to_pos(area_definition, j_new, i_new), errcheck=True, inverse=True)
    if np.any(j_displacement) or np.any(i_displacement):
        # Update values with displacement.
        j_old, i_old = j_new - j_displacement, i_new - i_displacement
        old_long, old_lat = p(*_pixel_to_pos(area_definition, j_old, i_old), errcheck=True, inverse=True)
    else:
        old_lat = new_lat
        old_long = new_long
    dims = None
    if np.size(old_lat) != 1:
        dims = ['y', 'x']
    if no_save is False:
        if displacement_data is None:
            raise ValueError('Cannot save data without displacement_data')
        save_data(displacement_data,
              (xarray.DataArray(_reshape(new_lat, shape), name='new_latitude', dims=dims,
                                attrs={'standard_name': 'latitude', 'grid_mapping': 'polar_stereographic',
                                       'units': 'degrees'}),
               xarray.DataArray(_reshape(new_long, shape), name='new_longitude', dims=dims,
                                attrs={'standard_name': 'longitude', 'grid_mapping': 'polar_stereographic',
                                       'units': 'degrees'}),
               xarray.DataArray(_reshape(old_lat, shape), name='old_latitude', dims=dims,
                                attrs={'standard_name': 'latitude', 'grid_mapping': 'polar_stereographic',
                                       'units': 'degrees'}),
               xarray.DataArray(_reshape(old_long, shape), name='old_longitude', dims=dims,
                                attrs={'standard_name': 'longitude', 'grid_mapping': 'polar_stereographic',
                                       'units': 'degrees'})))
    return shape, new_lat, new_long, old_lat, old_long


def _compute_vu(lat_ts, lat_0, long_0, delta_time, displacement_data=None, projection='stere', j=None, i=None,
                area_extent=None, shape=None, center=None, pixel_size=None, image_geod=None, earth_geod=None,
                no_save=True):
    if displacement_data is None:
        raise ValueError('displacement_data is required to find v and u but was not provided.')
    shape, new_lat, new_long, old_lat, old_long = _compute_lat_long(lat_ts, lat_0, long_0,
                                                                    displacement_data=displacement_data,
                                                                    projection=projection, j=j, i=i,
                                                                    area_extent=area_extent, shape=shape, center=center,
                                                                    pixel_size=pixel_size, image_geod=image_geod,
                                                                    no_save=no_save)
    lat_long_distance = _lat_long_dist((new_lat + old_lat) / 2, earth_geod)
    # u = (_delta_longitude(new_long, old_long) *
    #      _lat_long_dist(old_lat, earth_geod)[1] / (delta_time * 60) +
    #      _delta_longitude(new_long, old_long) *
    #      _lat_long_dist(new_lat, earth_geod)[1] / (delta_time * 60)) / 2
    # meters/second. distance is in meters delta_time is in minutes.
    v = (new_lat - old_lat) * lat_long_distance[0] / (delta_time * 60)
    u = np.vectorize(_delta_longitude)(new_long, old_long) * lat_long_distance[1] / (delta_time * 60)
    dims = None
    if np.size(v) != 1:
        dims = ['y', 'x']
    if no_save is False:
        save_data(displacement_data,
              (xarray.DataArray(_reshape(v, shape), name='v', dims=dims,
                                attrs={'standard_name': 'northward_wind', 'grid_mapping': 'polar_stereographic',
                                       'units': 'm/s'}),
               xarray.DataArray(_reshape(u, shape), name='u', dims=dims,
                                attrs={'standard_name': 'eastward_wind', 'grid_mapping': 'polar_stereographic',
                                       'units': 'm/s'})))
    return shape, v, u, new_lat, new_long


def _compute_velocity(lat_ts, lat_0, long_0, delta_time, displacement_data=None, projection='stere', j=None, i=None,
                      area_extent=None, shape=None, center=None, pixel_size=None, image_geod=None, earth_geod=None,
                      no_save=True):
    shape, v, u, new_lat, new_long = _compute_vu(lat_ts, lat_0, long_0, delta_time, displacement_data=displacement_data,
                                                 projection=projection, j=j, i=i, area_extent=area_extent, shape=shape,
                                                 center=center, pixel_size=pixel_size, image_geod=image_geod,
                                                 earth_geod=earth_geod, no_save=no_save)
    speed, angle = (u ** 2 + v ** 2) ** .5, ((90 - np.arctan2(v, u) * 180 / np.pi) + 360) % 360
    dims = None
    if np.size(speed) != 1:
        dims = ['y', 'x']
    if no_save is False:
         save_data(displacement_data,
              (xarray.DataArray(_reshape(speed, shape), name='speed', dims=dims,
                                attrs={'standard_name': 'wind_speed', 'grid_mapping': 'polar_stereographic',
                                       'units': 'm/s'}),
               xarray.DataArray(_reshape(angle, shape), name='angle', dims=dims,
                                attrs={'standard_name': 'wind_from_direction', 'grid_mapping': 'polar_stereographic',
                                       'units': 'degrees'})))
    # When wind vector azimuth is 0 degrees it points North (mathematically 90 degrees) and moves clockwise.
    return shape, speed, angle, v, u, new_lat, new_long


def _find_displacements_and_area(lat_ts=None, lat_0=None, long_0=None, displacement_data=None, projection='stere',
                                 j=None, i=None, area_extent=None, shape=None, center=None, pixel_size=None,
                                 image_geod=None, no_save=True):
    """Dynamically finds displacements and area of projection"""
    area_definition = None
    area_data = None
    if lat_0 is not None or long_0 is not None:
        try:
            area_data, area_definition = _create_area(lat_ts, lat_0, long_0, projection=projection,
                                                   area_extent=area_extent,
                                           shape=shape, center=center, pixel_size=pixel_size, image_geod=image_geod,
                                           displacement_data=displacement_data, no_save=no_save)
            if area_definition.y_size is not None and area_definition.x_size is not None:
                shape = (area_definition.y_size, area_definition.x_size)
        except ValueError:
            pass
    shape, j_displacement, i_displacement = _find_displacements(displacement_data, shape=shape, j=j, i=i,
                                                                no_save=no_save)
    if not isinstance(area_definition, AreaDefinition) and (lat_0 is not None or long_0 is not None):
        area_data, area_definition = _create_area(lat_ts, lat_0, long_0, projection=projection, area_extent=area_extent,
                                       shape=shape, center=center, pixel_size=pixel_size, image_geod=image_geod,
                                       displacement_data=displacement_data, no_save=no_save)
    return shape, j_displacement, i_displacement, area_definition, area_data


def area(lat_ts, lat_0, long_0, displacement_data=None, projection='stere', area_extent=None, shape=None, center=None,
         pixel_size=None, image_geod=None):
    """Dynamically computes area of projection.

    Parameters
    ----------
    lat_0 : float
        Normal latitude of projection
    long_0 : float
        Normal longitude of projection
    displacement_data : str or list, optional
        File or list containing displacements: [tag, width, height, i_11, j_11, i_12, j_12, ..., i_nm, j_nm] or
        [[j_displacement], [i_displacement]] respectively
    projection : str
        Name of projection that pixels are describing (stere, laea, merc, etc).
    area_extent : list, optional
        Area extent in projection units (lower_left_y, lower_left_x, upper_right_y, upper_right_x)
    shape : list, optional
        Number of pixels in the y and x direction following row-major format (height, width).
        Note that shape can be found from the displacement file or the area provided.
    center : list, optional
        Center of projection (lat, long)
    pixel_size : list or float, optional
        Size of pixels: (dy, dx)
    image_geod : string or Geod, optional
        Spheroid of projection (WGS84, sphere, etc)
    no_save : bool, optional
        When False, saves area to area.txt and wind_info.hdf5 (under the group "area")
        in a new directory by the name of the displacement file appended with "_output", which will be 
        created where the script was ran.

        Returns
        -------
            area : dict
                projection, lat_0 (degrees), long_0 (degrees), equatorial radius (meters),
                eccentricity, shape, area_extent (degrees), pixel_size (projection meters), center (degrees)
    """
    if not isinstance(lat_0, (int, float)) or not isinstance(long_0, (int, float)):
        raise ValueError(
            'lat_0 and long_0 must be ints or floats, but instead were ' + '{0} {1} and {2} {3} respectively'.format(
                lat_0, type(lat_0), long_0, type(long_0)))
    area_data = _find_displacements_and_area(lat_ts=lat_ts, lat_0=lat_0, long_0=long_0,
                                                   displacement_data=displacement_data,
                                                   projection=projection, area_extent=area_extent, shape=shape,
                                                   center=center, pixel_size=pixel_size, image_geod=image_geod)[4]
    return area_data


def displacements(lat_ts=None, lat_0=None, long_0=None, displacement_data=None, projection='stere', j=None, i=None,
                  area_extent=None, shape=None, center=None, pixel_size=None, image_geod=None):
    """Dynamically computes displacements.

    Parameters
    ----------
    lat_0 : float, optional
        Normal latitude of projection
    long_0 : float, optional
        Normal longitude of projection
    displacement_data : str or list, optional
        File or list containing displacements: [tag, width, height, i_11, j_11, i_12, j_12, ..., i_nm, j_nm] or
        [[j_displacement], [i_displacement]] respectively
    projection : str, optional
        Name of projection that pixels are describing (stere, laea, merc, etc).
    j : float or None, optional
        Row to run calculations on
    i : float or None, optional
        Column to run calculations on
    area_extent : list, optional
        Area extent in projection units [lower_left_y, lower_left_x, upper_right_y, upper_right_x]
    shape : list, optional
        Number of pixels in the y and x direction following row-major format (height, width).
        Note that shape can be found from the displacement file or the area provided.
    center : list, optional
        Center of projection (lat, long)
    pixel_size : list or float, optional
        Size of pixels: (dy, dx)
    image_geod : string or Geod, optional
        Spheroid of projection (WGS84, sphere, etc)
    no_save : bool, optional
        When False, saves displacements to j_displacement.txt, i_displacement.txt, and wind_info.hdf5
        (under the group "displacements") in a new directory by the name of the displacement file appended with 
        "_output", which will be created where the script was ran.

        Returns
        -------
            (j_displacements, i_displacements) : numpy.array or list
                j_displacements and i_displacements found in displacement file or list in row-major format
    """
    if displacement_data is None:
        raise ValueError('displacement_data is required to find displacements but was not provided.')
    if (not isinstance(lat_0, (int, float)) or not isinstance(long_0, (int, float))) and _not_none(
            [lat_0, long_0, area_extent, center, pixel_size, image_geod]):
        raise ValueError(
            'If lat_0 or long_0 were provided they both must be provided,'
            'but instead were {0} {1} and {2} {3}  respectively'.format(lat_0, type(lat_0), long_0, type(long_0)))
    shape, j_displacement, i_displacement = _find_displacements_and_area(lat_ts=lat_ts, lat_0=lat_0, long_0=long_0,
                                                                         displacement_data=displacement_data,
                                                                         projection=projection, j=j, i=i,
                                                                         area_extent=area_extent, shape=shape,
                                                                         center=center, pixel_size=pixel_size,
                                                                         image_geod=image_geod)[:3]
    return np.array((_reshape(j_displacement, shape), _reshape(i_displacement, shape)))


def velocity(lat_ts, lat_0, long_0, delta_time, displacement_data=None, projection='stere', j=None, i=None,
             area_extent=None, shape=None, center=None, pixel_size=None, image_geod=None, earth_geod=None):
    """Computes the speed and angle of the wind given an area and pixel-displacement.

    Parameters
    ----------
    lat_0 : float
        Normal latitude of projection
    long_0 : float
        Normal longitude of projection
    delta_time : int
        Amount of time that separates both files in minutes.
    displacement_data : str or list, optional
        File or list containing displacements: [tag, width, height, i_11, j_11, i_12, j_12, ..., i_nm, j_nm] or
        [[j_displacement], [i_displacement]] respectively
    projection : str
        Name of projection that the image is in (stere, laea, merc, etc).
    j : float or None, optional
        Row to run calculations on
    i : float or None, optional
        Column to run calculations on
    area_extent : list, optional
        Area extent in projection units [lower_left_y, lower_left_x, upper_right_y, upper_right_x]
    shape : list, optional
        Number of pixels in the y and x direction following row-major format (height, width).
        Note that shape can be found from the displacement file or the area provided.
    center : list, optional
        Center of projection (lat, long)
    pixel_size : list or float, optional
        Size of pixels: (dy, dx)
    image_geod : string or Geod, optional
        Spheroid of projection (WGS84, sphere, etc)
    earth_geod : string or Geod, optional
        Spheroid of Earth (WGS84, sphere, etc)
    no_save : bool, optional
        When false, saves velocity to speed.txt, angle.txt, and wind_info.hdf5 (under the group "velocity")
        in a new directory by the name of the displacement file appended with "_output", which will be 
        created where the script was ran.

    Returns
    -------
        (speed, angle) : numpy.array or list
            speed and angle (measured clockwise from north) of the wind calculated
            from area and pixel-displacement in row-major format
    """
    shape, speed, angle = _compute_velocity(lat_ts, lat_0, long_0, delta_time, displacement_data=displacement_data,
                                            projection=projection, j=j, i=i, area_extent=area_extent, shape=shape,
                                            center=center, pixel_size=pixel_size, image_geod=image_geod,
                                            earth_geod=earth_geod)[:3]
    return np.array((_reshape(speed, shape), _reshape(angle, shape)))


def vu(lat_ts, lat_0, long_0, delta_time, displacement_data=None, projection='stere', j=None, i=None, area_extent=None,
       shape=None, center=None, pixel_size=None, image_geod=None, earth_geod=None):
    """Computes the v and u components of the wind given an area and pixel-displacement.

    Parameters
    ----------
    lat_0 : float
        Normal latitude of projection
    long_0 : float
        Normal longitude of projection
    delta_time : int
        Amount of time that separates both files in minutes.
    displacement_data : str or list, optional
        File or list containing displacements: [tag, width, height, i_11, j_11, i_12, j_12, ..., i_nm, j_nm] or
        [[j_displacement], [i_displacement]] respectively
    projection : str
        Name of projection that pixels are describing (stere, laea, merc, etc).
    j : float or None, optional
        Row to run calculations on
    i : float or None, optional
        Column to run calculations on
    area_extent : list, optional
        Area extent in projection units [lower_left_y, lower_left_x, upper_right_y, upper_right_x]
    shape : list, optional
        Number of pixels in the y and x direction following row-major format (height, width).
        Note that shape can be found from the displacement file or the area provided.
    center : list, optional
        Center of projection (lat, long)
    pixel_size : list or float, optional
        Size of pixels: (dy, dx)
    image_geod : string or Geod, optional
        Spheroid of projection (WGS84, sphere, etc)
    earth_geod : string or Geod, optional
        Spheroid of Earth (WGS84, sphere, etc)
    no_save : bool, optional
        When False, saves vu to v.txt, u.txt, and wind_info.hdf5 (under the group "vu")
        in a new directory by the name of the displacement file appended with "_output", which will be 
        created where the script was ran.

    Returns
    -------
        (v, u) : numpy.array or list
            v and u components of wind calculated from area and pixel-displacement in row-major format
    """
    shape, v, u = _compute_vu(lat_ts, lat_0, long_0, delta_time, displacement_data=displacement_data,
                              projection=projection,
                              j=j, i=i, area_extent=area_extent, shape=shape, center=center, pixel_size=pixel_size,
                              image_geod=image_geod, earth_geod=earth_geod)[:3]
    return np.array((_reshape(v, shape), _reshape(u, shape)))


def lat_long(lat_ts, lat_0, long_0, displacement_data=None, projection='stere', j=None, i=None, area_extent=None,
             shape=None, center=None, pixel_size=None, image_geod=None):
    """Computes the latitude and longitude given an area and (j, i) values.

    Parameters
    ----------
    lat_0 : float
        Normal latitude of projection
    long_0 : float
        Normal longitude of projection
    displacement_data : str or list, optional
        File or list containing displacements: [tag, width, height, i_11, j_11, i_12, j_12, ..., i_nm, j_nm] or
        [[j_displacement], [i_displacement]] respectively
    projection : str
        Name of projection that pixels are describing (stere, laea, merc, etc).
    j : float or None, optional
        Row to run calculations on
    i : float or None, optional
        Column to run calculations on
    area_extent : list, optional
        Area extent in projection units [lower_left_y, lower_left_x, upper_right_y, upper_right_x]
    shape : list, optional
        Number of pixels in the y and x direction following row-major format (height, width).
        Note that shape can be found from the displacement file or the area provided.
    center : list, optional
        Center of projection (lat, long)
    pixel_size : list or float, optional
        Size of pixels: (dy, dx)
    image_geod : string or Geod, optional
        Spheroid of projection (WGS84, sphere, etc)
    no_save : bool, optional
        When False, saves lat_long to old_latitude.txt, old_longitude.txt, new_latitude.txt,
        new_longitude.txt, and wind_info.hdf5 (under the group "lat_long")
        in a new directory by the name of the displacement file appended with "_output", which will be 
        created where the script was ran.

    Returns
    -------
        (latitude, longitude) : numpy.array or list
            latitude and longitude calculated from area and pixel-displacement in row-major format
    """
    # If no displacements were given, then old=new
    shape, new_lat, new_long, old_lat, old_long = _compute_lat_long(lat_ts, lat_0, long_0,
                                                                    displacement_data=displacement_data,
                                                                    projection=projection, j=j, i=i,
                                                                    area_extent=area_extent, shape=shape, center=center,
                                                                    pixel_size=pixel_size, image_geod=image_geod)
    return np.array((_reshape(old_lat, shape), _reshape(old_long, shape)))


# TODO: indexing can go out of bounds.
def wind_info(lat_ts, lat_0, long_0, delta_time, displacement_data=None, projection='stere', j=None, i=None,
              area_extent=None,
              shape=None, center=None, pixel_size=None, image_geod=None, earth_geod=None, no_save=False):
    """Computes the latitude, longitude, velocity, angle, v, and u of the wind

    Parameters
    ----------
    lat_0 : float
        Normal latitude of projection
    long_0 : float
        Normal longitude of projection
    delta_time : int
        Amount of time that separates both files in minutes.
    displacement_data : str or list, optional
        File or list containing displacements: [tag, width, height, i_11, j_11, i_12, j_12, ..., i_nm, j_nm] or
        [[j_displacement], [i_displacement]] respectively
    projection : str
        Name of projection that pixels are describing (stere, laea, merc, etc).
    j : float or None, optional
        Row to run calculations on
    i : float or None, optional
        Column to run calculations on
    area_extent : list, optional
        Area extent in projection units [lower_left_y, lower_left_x, upper_right_y, upper_right_x]
    shape : list, optional
        Number of pixels in the y and x direction following row-major format (height, width).
        Note that shape can be found from the displacement file or the area provided.
    center : list, optional
        Center of projection (lat, long)
    pixel_size : list or float, optional
        Size of pixels: (dy, dx)
    image_geod : string or Geod, optional
        Spheroid of projection (WGS84, sphere, etc)
    earth_geod : string or Geod, optional
        Spheroid of Earth (WGS84, sphere, etc)
    no_save : bool, optional
        When False, saves wind_info to wind_info.txt and wind_info.hdf5 (under the group "wind_info")
        in a new directory by the name of the displacement file appended with "_output", which will be 
        created where the script was ran.

    Returns
    -------
        (latitude, longitude, velocity, angle, v, and u at each pixel) : numpy.array or list
            [latitude, longitude, velocity, angle, v, u] at each pixel in row-major format
    """
    shape, speed, angle, v, u, lat, long = _compute_velocity(lat_ts, lat_0, long_0, displacement_data=displacement_data,
                                                             projection=projection, j=j, i=i, delta_time=delta_time,
                                                             area_extent=area_extent, shape=shape, center=center,
                                                             pixel_size=pixel_size, image_geod=image_geod,
                                                             earth_geod=earth_geod, no_save=no_save)
    # Make each variable its own column.
    winds = np.insert(np.expand_dims(np.ravel(lat), axis=1), 1, long, axis=1)
    winds = np.insert(winds, 2, speed, axis=1)
    winds = np.insert(winds, 3, angle, axis=1)
    winds = np.insert(winds, 4, v, axis=1)
    winds = np.insert(winds, 5, u, axis=1)
    if np.shape(winds)[0] == 1:
        winds = winds[0]
        txt_shape = [1, 6]
        dims = None
    else:
        txt_shape = None
        dims = ['yx', 'vars']
    if no_save is False:
        save_data(displacement_data,
              [xarray.DataArray(winds, name='wind_info', dims=dims,
                                attrs={'standard_name': 'wind_speed',
                                       'description': 'new_lat, new_long, speed, angle, v, u',
                                       'grid_mapping': 'polar_stereographic'})])
    # Columns: lat, long, speed, direction, v, u
    return winds
