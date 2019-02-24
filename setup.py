#!/usr/bin/env python

from distutils.core import setup

setup(name='pywinds',
      version='1.0',
      author='William Roberts',
      author_email='wroberts4@wisc.edu',
      long_description=open('README.txt').read(),
      test_suite='pywinds.test.suite',
      setup_requires=['numpy', 'pyproj', 'pyresample', 'xarray'],
      install_requires=['numpy', 'pyproj', 'pyresample', 'xarray'])
