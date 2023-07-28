# Copyright (C) 2022-2023  C-PAC Developers

# This file is part of C-PAC.

# C-PAC is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.

# C-PAC is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public
# License for more details.

# You should have received a copy of the GNU Lesser General Public
# License along with C-PAC. If not, see <https://www.gnu.org/licenses/>.
FROM ghcr.io/fcp-indi/c-pac/stage-base:standard-v1.8.6.dev1
LABEL org.opencontainers.image.description "Full C-PAC image"
LABEL org.opencontainers.image.source https://github.com/FCP-INDI/C-PAC
USER root

# install C-PAC
COPY dev/circleci_data/pipe-test_ci.yml /cpac_resources/pipe-test_ci.yml
COPY . /code
RUN pip install -e /code
# set up runscript
COPY dev/docker_data /code/docker_data
RUN rm -Rf /code/docker_data/Dockerfiles && \
    mv /code/docker_data/* /code && \
    rm -Rf /code/docker_data && \
    chmod +x /code/run.py && \
    chmod +x /code/run-with-freesurfer.sh
ENTRYPOINT ["/code/run-with-freesurfer.sh"]

# link libraries & clean up
# link libraries & clean up
RUN rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /root/.cache/* \
    && find / -type f -print0 | sort -t/ -k2 | xargs -0 rdfind -makehardlinks true \
    && rm -rf results.txt \
    && apt-get remove rdfind -y \
    && apt-get clean \
    && apt-get autoremove -y \
    && ldconfig \
    && chmod 777 / \
    && chmod 777 $(ls / | grep -v sys | grep -v proc)

# set user
# USER c-pac_user