"""Unit tests for the AccessReportAggregator."""

import pytest
from app.models.schemas import PermissionLevel
from app.services.report_aggregator import AccessReportAggregator


def test_aggregate_basic_mapping(sample_graphql_repos_data):
    report = AccessReportAggregator.aggregate(
        organization="acme-corp",
        repositories_data=sample_graphql_repos_data,
        execution_time=0.5,
    )

    assert report.organization == "acme-corp"
    assert report.execution_time_seconds == 0.5
    assert len(report.users) == 4  # alice, bob, charlie, david

    # Check Alice
    alice = next(u for u in report.users if u.login == "alice")
    assert alice.name == "Alice Smith"
    assert alice.total_repositories_accessible == 1
    assert alice.highest_permission == PermissionLevel.ADMIN
    assert alice.repositories[0].name == "core-backend"
    assert alice.repositories[0].permission == PermissionLevel.ADMIN
    assert alice.repositories[0].is_private is True

    # Check Bob (has access to both core-backend and frontend-app)
    bob = next(u for u in report.users if u.login == "bob")
    assert bob.total_repositories_accessible == 2
    # Bob has WRITE on core-backend and MAINTAIN on frontend-app -> highest should be MAINTAIN
    assert bob.highest_permission == PermissionLevel.MAINTAIN
    repo_names = [r.name for r in bob.repositories]
    assert "core-backend" in repo_names
    assert "frontend-app" in repo_names


def test_aggregate_summary_metrics(sample_graphql_repos_data):
    report = AccessReportAggregator.aggregate(
        organization="acme-corp",
        repositories_data=sample_graphql_repos_data,
        execution_time=0.25,
        include_summary=True,
    )

    summary = report.summary
    assert summary is not None
    assert summary.total_repositories == 2
    assert summary.total_users == 4
    assert summary.private_repositories == 1
    assert summary.public_repositories == 1
    assert summary.permission_distribution["ADMIN"] == 1  # Alice
    assert summary.permission_distribution["MAINTAIN"] == 1  # Bob
    assert summary.permission_distribution["READ"] == 1  # Charlie
    assert summary.permission_distribution["TRIAGE"] == 1  # David


def test_aggregate_filter_by_min_permission(sample_graphql_repos_data):
    # Filter for users with at least WRITE permission
    report = AccessReportAggregator.aggregate(
        organization="acme-corp",
        repositories_data=sample_graphql_repos_data,
        execution_time=0.1,
        min_permission=PermissionLevel.WRITE,
    )

    # Only Alice (ADMIN) and Bob (WRITE/MAINTAIN) qualify
    assert len(report.users) == 2
    logins = [u.login for u in report.users]
    assert "alice" in logins
    assert "bob" in logins
    assert "charlie" not in logins
    assert "david" not in logins


def test_aggregate_filter_by_user(sample_graphql_repos_data):
    report = AccessReportAggregator.aggregate(
        organization="acme-corp",
        repositories_data=sample_graphql_repos_data,
        execution_time=0.1,
        target_user="alice",
    )

    assert len(report.users) == 1
    assert report.users[0].login == "alice"


def test_aggregate_filter_by_repository(sample_graphql_repos_data):
    report = AccessReportAggregator.aggregate(
        organization="acme-corp",
        repositories_data=sample_graphql_repos_data,
        execution_time=0.1,
        target_repo="frontend-app",
    )

    # In frontend-app, only Bob and David have access
    assert len(report.users) == 2
    logins = [u.login for u in report.users]
    assert "bob" in logins
    assert "david" in logins
    assert "alice" not in logins


def test_aggregate_empty_repositories():
    report = AccessReportAggregator.aggregate(
        organization="empty-org",
        repositories_data=[],
        execution_time=0.01,
        include_summary=True,
    )

    assert report.organization == "empty-org"
    assert len(report.users) == 0
    assert report.summary.total_repositories == 0
    assert report.summary.total_users == 0
