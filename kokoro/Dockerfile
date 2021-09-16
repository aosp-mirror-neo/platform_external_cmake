FROM centos:7

# centos-release-scl enables the repository containing devtoolset.
# perl is needed for the openssl Configure script.
RUN yum -y update && \
  yum -y install \
    centos-release-scl && \
  yum -y install \
    devtoolset-10-gcc \
    devtoolset-10-gcc-c++ \
    git \
    make \
    perl \
    python3
