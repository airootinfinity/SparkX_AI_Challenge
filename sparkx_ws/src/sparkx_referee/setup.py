from glob import glob

from setuptools import setup

package_name = 'sparkx_referee'
setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    package_data={package_name: ['web/*.html']},   # dashboard page (logos come from sparkx_worlds/brand)
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=False,
    maintainer='SparkX Organizers',
    maintainer_email='organizers@sparkx.example',
    description='SparkX referee and mission server',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'referee = sparkx_referee.referee_node:main',
        'leaderboard = sparkx_referee.leaderboard:main',
    ]},
)
