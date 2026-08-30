"""The `/healthz` liveness probe (docs/ops/aws-deploy-from-scratch.md §14).

The ALB target group health-checks this path, so it must: respond 200 without
authentication, return the documented JSON body, and not depend on the database
(a DB outage must not make every task fail its health check and get replaced).
"""
import pytest
from django.test import Client


def test_healthz_is_public_and_ok():
    resp = Client().get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.django_db
def test_healthz_does_not_hit_the_database(django_assert_num_queries):
    with django_assert_num_queries(0):
        Client().get("/healthz")
