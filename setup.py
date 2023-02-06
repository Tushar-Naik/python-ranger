# Copyright 2022. Tushar Naik
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# please install python if it is not present in the system
from setuptools import setup, find_packages

with open("README.md", "r") as fh:
    long_description = fh.read()


setup(
    name='python-ranger-tn',
    version='1.8.4',
    packages=find_packages(),
    license=' License 2.0',
    description='The python equivalent for ranger based service discovery mechanism using zookeeper',
    author='Tushar Naik',
    author_email='tushar.knaik@gmail.com',
    keywords=['ranger', 'zookeeper', 'service discovery', 'periodic task', 'interval', 'periodic job', 'flask style',
              'decorator', 'tushar'],
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Tushar-Naik/python-ranger-daemon",
    include_package_data=True,
    install_requires=[
        'requests',
        'kazoo',
        'python_daemon'
    ],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: Implementation :: PyPy',
        'Topic :: Utilities',
        'Topic :: System :: Networking',
        'Topic :: System :: Distributed Computing'
    ],
)
