import secrets
from datetime import datetime, timedelta, timezone

import click
from googleapiclient.errors import HttpError

from bamboogooglesync.google import create_directory_service

from .bamboo import BambooSession
from .options import *


@click.group()
def cli(*args, **kwargs):
    pass


@cli.command()
@bamboo_subdomain
@bamboo_api_key
@google_admin
@google_credentials
def update(
    bamboo_subdomain,
    bamboo_api_key,
    google_admin,
    google_credentials,
):
    b = BambooSession(bamboo_subdomain, bamboo_api_key)
    g = create_directory_service(google_admin, google_credentials)

    directory = b.get("/employees/directory")
    for employee in directory.get("employees"):
        update_kwargs = {
            "userKey": employee["workEmail"],
            "body": {
                "externalIds": [{"value": employee["id"], "type": "organization"}],
                "orgUnitPath": f'/{employee["department"]}',
            },
        }
        try:
            g.users().update(**update_kwargs).execute()
            click.echo({"type": "update_user", **update_kwargs})
        except HttpError as e:
            echo_http_error(e, **update_kwargs)
            continue


@cli.command()
@bamboo_subdomain
@bamboo_api_key
@google_admin
@google_credentials
def sync(
    bamboo_subdomain,
    bamboo_api_key,
    google_admin,
    google_credentials,
):
    b = BambooSession(bamboo_subdomain, bamboo_api_key)
    g = create_directory_service(google_admin, google_credentials)

    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
        "%Y-%m-%dT%H:%M:%S%z"
    )

    changes = b.get("/employees/changed", params={"type": "inserted", "since": since})
    for employee_id in changes["employees"] or []:
        employee = b.get(
            f"/employees/{employee_id}",
            params={
                "fields": ",".join(
                    [
                        "workEmail",
                        "preferredName",
                        "firstName",
                        "lastName",
                        "status",
                        "homeEmail",
                        "jobTitle",
                        "supervisorEmail",
                        "department",
                    ]
                )
            },
        )

        insert_kwargs = {
            "body": {
                "primaryEmail": employee["workEmail"],
                "name": {
                    "givenName": employee["preferredName"] or employee["firstName"],
                    "familyName": employee["lastName"],
                },
                "suspended": employee["status"] != "Active",
                "password": secrets.token_urlsafe(32),
                "changePasswordAtNextLogin": True,
                "emails": [
                    {
                        "address": employee["homeEmail"],
                        "type": "home",
                    },
                    {
                        "address": employee["workEmail"],
                        "primary": True,
                    },
                ],
                "relations": [
                    {"value": employee["supervisorEmail"], "type": "manager"}
                ],
                "organizations": [
                    {
                        "title": employee["jobTitle"],
                        "primary": True,
                        "department": employee["department"],
                    }
                ],
                "externalIds": [{"value": employee["id"], "type": "organization"}],
                "orgUnitPath": f'/{employee["department"]}',
            }
        }
        try:
            g.users().insert(**insert_kwargs).execute()
            click.echo({"type": "insert_user", **insert_kwargs})
        except HttpError as e:
            echo_http_error(e, **insert_kwargs)
            continue

    b.get("/employees/changed", params={"type": "updated", "since": since})
    for employee_id in changes["employees"] or []:
        employee = b.get(
            f"/employees/{employee_id}",
            params={
                "fields": ",".join(
                    [
                        "workEmail",
                        "preferredName",
                        "firstName",
                        "lastName",
                        "status",
                        "homeEmail",
                        "jobTitle",
                        "supervisorEmail",
                        "department",
                    ]
                )
            },
        )

        try:
            user = get_user_by_external_id(g, employee["id"])
        except HttpError as e:
            echo_http_error(e)
            continue
        except NotFoundError as e:
            echo_not_found_error(e)
            continue

        user = res["users"][0]
        update_kwargs = {
            "userKey": user["id"],
            "body": {
                "primaryEmail": employee["workEmail"],
                "name": {
                    "givenName": employee["preferredName"] or employee["firstName"],
                    "familyName": employee["lastName"],
                },
                "suspended": employee["status"] != "Active",
                "emails": [
                    {
                        "address": employee["homeEmail"],
                        "type": "home",
                    },
                    {
                        "address": employee["workEmail"],
                        "primary": True,
                    },
                ],
                "relations": [
                    {"value": employee["supervisorEmail"], "type": "manager"}
                ],
                "organizations": [
                    {
                        "title": employee["jobTitle"],
                        "primary": True,
                        "department": employee["department"],
                    }
                ],
                "orgUnitPath": f'/{employee["department"]}',
            },
        }
        try:
            g.users().update(**update_kwargs).execute()
            click.echo({"type": "update_user", **update_kwargs})
        except HttpError as e:
            echo_http_error(e, **update_kwargs)
            continue

    changes = b.get("/employees/changed", params={"type": "deleted", "since": since})
    for employee_id in changes["employees"] or []:
        try:
            user = get_user_by_external_id(g, employee_id)
        except HttpError as e:
            echo_http_error(e)
            continue
        except NotFoundError as e:
            echo_not_found_error(e)
            continue

        delete_kwargs = {"userKey": user["id"]}
        try:
            g.users().delete(**delete_kwargs).execute()
            click.echo({"type": "delete_user", **delete_kwargs})
        except HttpError as e:
            echo_http_error(e, **delete_kwargs)


def get_user_by_external_id(g, external_id):
    list_kwargs = {
        "customer": "my_customer",
        "query": f"externalId={external_id}",
        "maxResults": 1,
    }
    res = g.users().list(**list_kwargs).execute()

    if "users" not in res:
        raise NotFoundError(f"User with external id {external_id} not found")

    return res["users"][0]


def echo_http_error(e, **kwargs):
    click.echo(
        {
            "type": "error",
            "status_code": e.status_code,
            "reason": e.reason,
            "error_details": e.error_details,
            **kwargs,
        }
    )


def echo_not_found_error(e):
    click.echo({"type": "error", "cause": str(e)})


class NotFoundError(Exception):
    pass


if __name__ == "__main__":
    cli()