# please install python if it is not present in the system
from setuptools import setup
import serviceprovider

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name=serviceprovider.__name__,
    version=serviceprovider.__version__,
    packages=['serviceprovider'],
    license=' License 2.0',
    description='A service discovery service provider using zookeeper for providing updates',
    author='Tushar Naik',
    author_email='tushar.knaik@gmail.com',
    keywords=['ranger', 'zookeeper', 'service discovery', 'periodic task', 'interval', 'periodic job', 'flask style',
              'decorator'],
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Tushar-Naik/python-ranger-daemon",
    include_package_data=True,
    py_modules=['serviceprovider'],
)
