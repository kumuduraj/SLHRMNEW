from setuptools import setup, find_packages

setup(
    name="slhrm",
    version="0.0.1",
    description="Biometric fingerprint attendance for ERPNext v16",
    author="Evonet",
    author_email="rajitha@evonet.lk",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=["frappe"],
)