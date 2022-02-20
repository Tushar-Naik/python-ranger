# please install python if it is not present in the system
from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()


setup(
    name='serviceprovider',
    version='1.6.4',
    packages=['serviceprovider'],
    license=' License 2.0',
    description='The python equivalent for ranger based service discovery mechanism using zookeeper',
    author='Tushar Naik',
    author_email='tushar.knaik@gmail.com',
    keywords=['ranger', 'zookeeper', 'service discovery', 'periodic task', 'interval', 'periodic job', 'flask style',
              'decorator'],
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Tushar-Naik/python-ranger-daemon",
    include_package_data=True,
    py_modules=['serviceprovider'],
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
