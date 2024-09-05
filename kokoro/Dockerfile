FROM rockylinux:8

# centos-release-scl enables the repository containing devtoolset.
# perl is needed for the openssl Configure script.
RUN yum -y update && \
  yum -y install \
    gcc-toolset-10-gcc \
    gcc-toolset-10-gcc-c++ \
    git \
    make \
    perl \
    perl-IPC-Cmd \
    python3
