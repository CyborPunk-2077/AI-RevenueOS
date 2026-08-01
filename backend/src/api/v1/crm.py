"""Contact and account endpoints.

Same shape as `leads.py`: parse, authorise, delegate, envelope. No ORM access and
no provider calls at this layer -- `import-linter` enforces that, not convention.

Every route names its permission explicitly rather than relying on the service to
check. The service enforces *scope*; the route enforces *capability*. Both are
needed: an Agent may hold `contact:read` and still only be entitled to their own
records.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from api.app.envelope import success
from api.deps.idempotency import parse_if_match
from api.deps.principal import CurrentPrincipal, ListQuery, list_query
from api.v1.schemas import AccountCreate, AccountUpdate, ContactCreate, ContactUpdate

contacts_router = APIRouter(prefix="/contacts", tags=["crm"])
accounts_router = APIRouter(prefix="/accounts", tags=["crm"])

SearchQuery = Annotated[str | None, Query(max_length=200, description="Substring match")]


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


# --- contacts ---------------------------------------------------------------


@contacts_router.get("", summary="List and search contacts")
async def list_contacts(
    request: Request,
    principal: CurrentPrincipal,
    query: Annotated[ListQuery, Depends(list_query)],
    search: SearchQuery = None,
) -> dict[str, Any]:
    principal.require("contact", "list")
    from application.crm.service import ContactService

    page = await ContactService.for_principal(principal).list_contacts(query, search=search)
    return success(
        {"contacts": page.items},
        pagination=page.meta(),
        request_id=_request_id(request),
    )


@contacts_router.post("", status_code=status.HTTP_201_CREATED, summary="Create a contact")
async def create_contact(
    payload: ContactCreate,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    principal.require("contact", "create")
    from application.crm.service import ContactService

    contact = await ContactService.for_principal(principal).create(payload.model_dump())
    response.headers["ETag"] = f'W/"{contact["version"]}"'
    return success(contact, request_id=_request_id(request))


@contacts_router.get("/{contact_id}", summary="Read a contact")
async def read_contact(
    contact_id: UUID, request: Request, response: Response, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("contact", "read")
    from application.crm.service import ContactService

    contact = await ContactService.for_principal(principal).get(contact_id)
    response.headers["ETag"] = f'W/"{contact["version"]}"'
    return success(contact, request_id=_request_id(request))


@contacts_router.patch("/{contact_id}", summary="Update a contact")
async def update_contact(
    contact_id: UUID,
    payload: ContactUpdate,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    if_match: Annotated[int | None, Depends(parse_if_match)] = None,
) -> dict[str, Any]:
    principal.require("contact", "update")
    from application.crm.service import ContactService

    # `exclude_unset` is what makes `account_id: null` mean "unlink" while an
    # omitted `account_id` means "leave it alone".
    contact = await ContactService.for_principal(principal).update(
        contact_id, payload.model_dump(exclude_unset=True), expected_version=if_match
    )
    response.headers["ETag"] = f'W/"{contact["version"]}"'
    return success(contact, request_id=_request_id(request))


# --- accounts ---------------------------------------------------------------


@accounts_router.get("", summary="List and search accounts")
async def list_accounts(
    request: Request,
    principal: CurrentPrincipal,
    query: Annotated[ListQuery, Depends(list_query)],
    search: SearchQuery = None,
) -> dict[str, Any]:
    principal.require("account", "list")
    from application.crm.service import AccountService

    page = await AccountService.for_principal(principal).list_accounts(query, search=search)
    return success(
        {"accounts": page.items},
        pagination=page.meta(),
        request_id=_request_id(request),
    )


@accounts_router.post("", status_code=status.HTTP_201_CREATED, summary="Create an account")
async def create_account(
    payload: AccountCreate,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    principal.require("account", "create")
    from application.crm.service import AccountService

    account = await AccountService.for_principal(principal).create(payload.model_dump())
    response.headers["ETag"] = f'W/"{account["version"]}"'
    return success(account, request_id=_request_id(request))


@accounts_router.get("/{account_id}", summary="Read an account")
async def read_account(
    account_id: UUID, request: Request, response: Response, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("account", "read")
    from application.crm.service import AccountService

    account = await AccountService.for_principal(principal).get(account_id)
    response.headers["ETag"] = f'W/"{account["version"]}"'
    return success(account, request_id=_request_id(request))


@accounts_router.patch("/{account_id}", summary="Update an account")
async def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    if_match: Annotated[int | None, Depends(parse_if_match)] = None,
) -> dict[str, Any]:
    principal.require("account", "update")
    from application.crm.service import AccountService

    account = await AccountService.for_principal(principal).update(
        account_id, payload.model_dump(exclude_unset=True), expected_version=if_match
    )
    response.headers["ETag"] = f'W/"{account["version"]}"'
    return success(account, request_id=_request_id(request))


@accounts_router.get("/{account_id}/contacts", summary="Contacts linked to an account")
async def account_contacts(
    account_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("account", "read")
    principal.require("contact", "list")
    from application.crm.service import AccountService

    contacts = await AccountService.for_principal(principal).contacts_for(account_id)
    return success({"contacts": contacts}, request_id=_request_id(request))
