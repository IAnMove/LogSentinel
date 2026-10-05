"""A destination URL may not reach cloud metadata by hiding its IPv4 address inside an IPv6 one."""

import pytest

from logsentinel.portal.models import check_url

METADATA = "169.254.169.254"


@pytest.mark.parametrize(
    "url",
    [
        f"http://{METADATA}/latest/meta-data",
        "http://[::ffff:169.254.169.254]/",
        "http://[::ffff:a9fe:a9fe]/",
        "http://[64:ff9b::a9fe:a9fe]/",
        "http://[64:ff9b::169.254.169.254]/",
        "http://[2002:a9fe:a9fe::1]/",
        "http://[2002:a9fe:a9fe:1:2:3:4:5]/",
        "http://metadata/computeMetadata/v1/",
        "http://METADATA./",
        "http://metadata.google.internal/",
        "http://0xa9fea9fe/",
        "http://2852039166/",
        "http://[fe80::1]/",
    ],
)
def test_addresses_that_reach_cloud_metadata_are_refused(url):
    with pytest.raises(ValueError):
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.10:11434",
        "http://127.0.0.1:8080/v1",
        "http://10.0.0.5/",
        "https://hooks.example.com/services/x",
        "http://[64:ff9b::808:808]/",
        "http://[2002:808:808::1]/",
        "http://[::1]:8080/",
        "http://metadata-service.example.com/",
    ],
)
def test_ordinary_lan_and_public_addresses_stay_allowed(url):
    assert check_url(url) == url
