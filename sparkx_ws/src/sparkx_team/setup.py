from glob import glob

from setuptools import setup

package_name = 'sparkx_team'
setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/team.yaml']),
        ('share/' + package_name + '/models', glob('models/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=False,
    maintainer='SparkX Organizers',
    maintainer_email='organizers@sparkx.example',
    description='SparkX team package (the only files a team may edit)',
    license='Apache-2.0',
    # Entry points are fixed: the locked launch starts exactly these three executables.
    entry_points={'console_scripts': [
        'perception = sparkx_team.perception:main',
        'memory = sparkx_team.memory:main',
        'mission = sparkx_team.mission:main',
    ]},
)
