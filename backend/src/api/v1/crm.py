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
from api.v1.schemas import (
    AccountCreate,
    AccountUpdate,
    ActivityLogRequest,
    ContactCreate,
    ContactUpdate,
    DealCreate,
    DealStageMoveRequest,
    DealUpdate,
    NoteCreateRequest,
    NoteUpdateRequest,
)

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


# --- timeline: activities and notes ------------------------------------------
#
# Mounted under both parents. The service resolves the parent through the scoped
# repository first, so a timeline on another tenant's record is a 404 rather than
# an empty list -- an empty list would confirm the id exists.

notes_router = APIRouter(prefix="/notes", tags=["crm"])


def _timeline(principal: Any) -> Any:
    from application.crm.timeline import TimelineService

    return TimelineService.for_principal(principal)


@contacts_router.get("/{contact_id}/timeline", summary="Activities and notes for a contact")
async def contact_timeline(
    contact_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("contact", "read")
    principal.require("activity", "list")
    entries = await _timeline(principal).timeline("contact", contact_id)
    return success({"timeline": entries}, request_id=_request_id(request))


@contacts_router.post(
    "/{contact_id}/activities", status_code=status.HTTP_201_CREATED, summary="Log an activity"
)
async def log_contact_activity(
    contact_id: UUID, payload: ActivityLogRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("activity", "create")
    entry = await _timeline(principal).log_activity("contact", contact_id, payload.model_dump())
    return success(entry, request_id=_request_id(request))


@contacts_router.post(
    "/{contact_id}/notes", status_code=status.HTTP_201_CREATED, summary="Add a note"
)
async def add_contact_note(
    contact_id: UUID, payload: NoteCreateRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("note", "create")
    entry = await _timeline(principal).add_note("contact", contact_id, payload.model_dump())
    return success(entry, request_id=_request_id(request))


@accounts_router.get("/{account_id}/timeline", summary="Activities and notes for an account")
async def account_timeline(
    account_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("account", "read")
    principal.require("activity", "list")
    entries = await _timeline(principal).timeline("account", account_id)
    return success({"timeline": entries}, request_id=_request_id(request))


@accounts_router.post(
    "/{account_id}/activities", status_code=status.HTTP_201_CREATED, summary="Log an activity"
)
async def log_account_activity(
    account_id: UUID, payload: ActivityLogRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("activity", "create")
    entry = await _timeline(principal).log_activity("account", account_id, payload.model_dump())
    return success(entry, request_id=_request_id(request))


@accounts_router.post(
    "/{account_id}/notes", status_code=status.HTTP_201_CREATED, summary="Add a note"
)
async def add_account_note(
    account_id: UUID, payload: NoteCreateRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("note", "create")
    entry = await _timeline(principal).add_note("account", account_id, payload.model_dump())
    return success(entry, request_id=_request_id(request))


@notes_router.patch("/{note_id}", summary="Edit your own note")
async def update_note(
    note_id: UUID,
    payload: NoteUpdateRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    if_match: Annotated[int | None, Depends(parse_if_match)] = None,
) -> dict[str, Any]:
    principal.require("note", "update")
    # Authorship is enforced in the service: `note:update` is not a licence to
    # rewrite a colleague's note under their name.
    note = await _timeline(principal).update_note(
        note_id, payload.model_dump(exclude_unset=True), expected_version=if_match
    )
    response.headers["ETag"] = f'W/"{note["version"]}"'
    return success(note, request_id=_request_id(request))


# --- deals and pipelines -----------------------------------------------------

deals_router = APIRouter(prefix="/deals", tags=["crm"])


def _deals(principal: Any) -> Any:
    from application.crm.deals import DealService

    return DealService.for_principal(principal)


@deals_router.get("/board", summary="The pipeline as stage columns")
async def deal_board(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    principal.require("deal", "list")
    board = await _deals(principal).board()
    return success(board, request_id=_request_id(request))


@deals_router.get("", summary="List deals")
async def list_deals(
    request: Request,
    principal: CurrentPrincipal,
    query: Annotated[ListQuery, Depends(list_query)],
    deal_status: Annotated[str | None, Query(alias="status", max_length=20)] = None,
) -> dict[str, Any]:
    principal.require("deal", "list")
    page = await _deals(principal).list_deals(query, status=deal_status)
    return success({"deals": page.items}, pagination=page.meta(), request_id=_request_id(request))


@deals_router.post("", status_code=status.HTTP_201_CREATED, summary="Create a deal")
async def create_deal(
    payload: DealCreate, request: Request, response: Response, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("deal", "create")
    deal = await _deals(principal).create(payload.model_dump())
    response.headers["ETag"] = f'W/"{deal["version"]}"'
    return success(deal, request_id=_request_id(request))


@deals_router.get("/{deal_id}", summary="Read a deal")
async def read_deal(
    deal_id: UUID, request: Request, response: Response, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("deal", "read")
    deal = await _deals(principal).get(deal_id)
    response.headers["ETag"] = f'W/"{deal["version"]}"'
    return success(deal, request_id=_request_id(request))


@deals_router.patch("/{deal_id}", summary="Update a deal")
async def update_deal(
    deal_id: UUID,
    payload: DealUpdate,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    if_match: Annotated[int | None, Depends(parse_if_match)] = None,
) -> dict[str, Any]:
    principal.require("deal", "update")
    deal = await _deals(principal).update(
        deal_id, payload.model_dump(exclude_unset=True), expected_version=if_match
    )
    response.headers["ETag"] = f'W/"{deal["version"]}"'
    return success(deal, request_id=_request_id(request))


@deals_router.post("/{deal_id}/stage", summary="Move a deal to another stage")
async def move_deal_stage(
    deal_id: UUID,
    payload: DealStageMoveRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    if_match: Annotated[int | None, Depends(parse_if_match)] = None,
) -> dict[str, Any]:
    principal.require("deal", "update")
    # Every rule -- required fields, direction, loss reason, resulting status --
    # comes from `domain/deals/pipeline_policy.py`, not from this layer.
    deal = await _deals(principal).move_stage(
        deal_id,
        payload.stage_id,
        loss_reason=payload.loss_reason,
        expected_version=if_match,
    )
    response.headers["ETag"] = f'W/"{deal["version"]}"'
    return success(deal, request_id=_request_id(request))


@deals_router.post("/{deal_id}/reopen", summary="Reopen a closed deal")
async def reopen_deal(
    deal_id: UUID,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    if_match: Annotated[int | None, Depends(parse_if_match)] = None,
) -> dict[str, Any]:
    principal.require("deal", "update")
    deal = await _deals(principal).reopen(deal_id, expected_version=if_match)
    response.headers["ETag"] = f'W/"{deal["version"]}"'
    return success(deal, request_id=_request_id(request))
