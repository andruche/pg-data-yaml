from setuptools import find_packages, setup

from pg_data_yaml import __version__

PACKAGE_NAME = 'pg-data-yaml'
PACKAGE_DESC = 'Yaml data converter between DB and Repo'
PACKAGE_VERSION = __version__

install_requires = [
    'pyyaml',
    'asyncpg>=0.27.0,<0.31.0',
]

tests_require = [
    'flake8>=5,<6',
    'pytest>=8,<9',
    'pytest-cov',
    'pytest-flake8',
    'pytest-asyncio',
    'pytest-sugar',
]

console_scripts = [
    'pg_data_yaml=pg_data_yaml.main:main',
]


def readme():
    with open('README.md', 'r') as f:
        return f.read()


setup(
    name=PACKAGE_NAME,
    version=PACKAGE_VERSION,
    description=PACKAGE_DESC,
    long_description=readme(),
    long_description_content_type='text/markdown',
    url='https://github.com/andruche/pg-data-yaml',
    project_urls={
        'Documentation': 'https://github.com/andruche/pg-data-yaml/blob/master/README.md',
        'Bug Tracker': 'https://github.com/andruche/pg-data-yaml/issues',
    },
    author='Andrey Chernyakov',
    license='BSD',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
    ],
    zip_safe=False,
    packages=find_packages(exclude=['tests', '.reports']),
    entry_points={'console_scripts': console_scripts},
    python_requires='>=3.8',
    install_requires=install_requires,
    extras_require={'dev': tests_require},
    keywords='postgres,postgresql,yaml,reference-data',
)
