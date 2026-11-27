# INT-18F: CLI-only, fixture-only image. No web server or live credential path.
FROM wordpress:php8.3-apache@sha256:9b46af6a41fd0dcb2e5cf85033a6350d05010356847ede1cfcac5cf94292eb26 AS wordpress-core
FROM wordpress:cli-php8.3@sha256:fc50189ac8d3256891d0d964f8d80cf62189eb6262f53c7fd8bfc40debd71029
USER root
WORKDIR /opt/bakata
COPY --from=wordpress-core /usr/src/wordpress/ /opt/bakata/wp/
COPY plugins/ /opt/bakata/wp/wp-content/plugins/
COPY sandbox-fixture.php /opt/bakata/wp/wp-content/mu-plugins/sandbox-fixture.php
COPY wp-config.php /opt/bakata/wp/wp-config.php
COPY dropify-capture-page.php /opt/bakata/dropify-capture-page.php
COPY run-fixture.sh /opt/bakata/run-fixture.sh
COPY validate-request.php /opt/bakata/validate-request.php
COPY catalog-egress-policy.php /opt/bakata/catalog-egress-policy.php
RUN chmod 0555 /opt/bakata/run-fixture.sh && chmod -R a+rX /opt/bakata/wp
RUN mkdir /exchange && chown 33:33 /exchange && chmod 0700 /exchange && chmod 1777 /tmp
VOLUME ["/tmp","/exchange"]
ENV HOME=/tmp WP_CLI_CACHE_DIR=/tmp/wp-cli-cache BAKATA_DROPIFY_SANDBOX=1
USER 33:33
ENTRYPOINT ["/bin/sh","/opt/bakata/run-fixture.sh"]
