from glob import glob

from setuptools import setup

package_name = 'sparkx_bringup'
setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=False,
    maintainer='SparkX Organizers',
    maintainer_email='organizers@sparkx.example',
    description='SparkX bringup launches and tools',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'teleop = sparkx_bringup.teleop:main',
        'dataset_capture = sparkx_bringup.dataset_capture:main',
    ]},
)
