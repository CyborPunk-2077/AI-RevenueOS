"""Seed the Sangam dogfood tenant: the founders' own prospecting workspace. LOCAL ONLY.

This is not a fixture file. It is the business Sangam is being built to run - an
SME-automation consultancy in Bengaluru selling to other Indian SMEs - populated
with the state such a business is actually in on a Tuesday morning: some enquiries
nobody has touched, some follow-ups already overdue, a duplicate nobody merged, a
deal that was lost for a reason worth remembering.

Every timestamp is relative to the moment of seeding, so "overdue by two days"
stays true whenever the demo is run. That is the whole point: a leakage-prevention
product demonstrated on data with no leakage in it demonstrates nothing.

By default this is *additive and idempotent* - if the tenant already holds leads,
nothing is rewritten, because the founders are expected to use this workspace for
real prospecting. `--refresh` rebuilds the synthetic rows and is the only path
that deletes anything, and it only ever touches this one tenant.

    python src/scripts/seed_sangam.py
    DEMO_PASSWORD='choose-your-own' python src/scripts/seed_sangam.py --refresh
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from application.tenants.demo_data import empty_manifest, record_manifest
from application.tenants.provisioning import (
    FOUNDER,
    TEST,
    Person,
    WorkspaceSpec,
    provision_workspace,
)
from domain.auth.permissions import Role
from infrastructure.auth.passwords import hash_password, validate_password
from infrastructure.database.models.crm import (
    Account,
    Activity,
    Contact,
    Deal,
    Note,
    Pipeline,
    Stage,
    Task,
)
from infrastructure.database.models.leads import Lead, LeadDuplicateCandidate
from infrastructure.database.models.tenancy import Team
from infrastructure.database.session import admin_session, tenant_session
from infrastructure.logging.setup import configure_logging, get_logger
from shared.settings import get_settings
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

logger = get_logger("scripts.seed_sangam")

SANGAM_ID = UUID("01890000-0000-7000-8000-00000005a76a")

#: A second, deliberately empty workspace that exists only for the browser tests.
#:
#: The founders are about to run their real prospecting out of the `sangam`
#: workspace. A browser suite that invents three businesses per run would fill
#: their prospect list with rubbish within a week, and the obvious workarounds are
#: worse: deleting rows afterwards fights the append-only activity trail, and an
#: `is_test` column on every business entity spreads a testing concern through the
#: data model. Tenancy already draws exactly this boundary and is enforced all the
#: way down to row-level security, so the tests get their own tenant and the
#: founders' workspace is never written to.
SANGAM_E2E_ID = UUID("01890000-0000-7000-8000-0000000e2e00")

# The founders and the one salesperson. Scope differs on purpose: Kiran sees only
# his own prospects, which is what makes "clear ownership" visible rather than
# asserted.
TEAM: tuple[tuple[str, str, Role, str], ...] = (
    ("abhishek@sangam.co.in", "Abhishek Jindal", Role.OWNER, "global"),
    ("priya@sangam.co.in", "Priya Nair", Role.MANAGER, "team"),
    ("kiran@sangam.co.in", "Kiran Deshpande", Role.MEMBER, "self"),
)

#: The test workspace needs an owner to sign in as and one colleague to assign
#: work to, and nothing else. It is never seeded with prospects: every scenario
#: creates exactly what it asserts on.
E2E_TEAM: tuple[tuple[str, str, Role, str], ...] = (
    ("owner@sangam-e2e.test", "Test Owner", Role.OWNER, "global"),
    ("rep@sangam-e2e.test", "Test Rep", Role.MANAGER, "team"),
)

#: A third workspace, shaped exactly like a real pilot, that the session-5 browser
#: acceptance drives.
#:
#: It is stamped `test`, not `pilot`, and that is deliberate. A `pilot` workspace
#: counts as real data everywhere it matters - `founder_data_report.py` counts it,
#: and `RESET_DEMO` refuses while it exists - so labelling a workspace that
#: browser tests write to as a pilot would make every reset look dangerous for no
#: reason, which is how a safety prompt stops being read.
#:
#: What it *does* prove is the thing the pilot depends on: it is provisioned by
#: the same `provision_workspace` call, with all three roles and their real
#: scopes, so a manager here has a team for the same reason a pilot manager does.
#: Provisioning of a genuinely pilot-kind workspace is proven separately, against
#: a throwaway tenant, in `tests/integration/test_pilot_provisioning.py`.
SANGAM_PILOT_E2E_ID = UUID("01890000-0000-7000-8000-0000000b1107")

PILOT_E2E_TEAM: tuple[tuple[str, str, Role, str], ...] = (
    ("owner@pilot-e2e.test", "Pilot Owner", Role.OWNER, "global"),
    ("manager@pilot-e2e.test", "Pilot Manager", Role.MANAGER, "team"),
    ("sales@pilot-e2e.test", "Pilot Salesperson", Role.MEMBER, "self"),
)

MINUTE = 60


def _hours(n: float) -> timedelta:
    return timedelta(hours=n)


def _days(n: float) -> timedelta:
    return timedelta(days=n)


# --- the prospect book -------------------------------------------------------
#
# Real Bengaluru SME shapes: a dental chain, a coaching institute, a logistics
# operator. `owner` is the person Sangam actually speaks to. `age_days` is how
# long ago the enquiry arrived, and `responded_after_hours` is None when nobody
# has replied yet - which is exactly the row the dashboard has to surface.

PROSPECTS: tuple[dict[str, Any], ...] = (
    # --- untouched enquiries: the leakage the product exists to prevent -------
    {
        "key": "shreya-dental",
        "first_name": "Shreya",
        "last_name": "Bhat",
        "email": "shreya@smilecraftdental.in",
        "phone": "+919845012201",
        "company": "SmileCraft Dental Care",
        "industry": "Dental clinics",
        "location": "Indiranagar, Bengaluru",
        "employees": 14,
        "source": "web_form",
        "requirement": (
            "Three branches, appointment reminders sent by hand. Wants missed-call follow-up. "
        ),
        "age_days": 2.1,
        "responded_after_hours": None,
        "status": "new",
        "owner": None,
        "score": None,
    },
    {
        "key": "rahul-fitness",
        "first_name": "Rahul",
        "last_name": "Menon",
        "email": "rahul.menon@pulsefitness.co.in",
        "phone": "+919845012202",
        "company": "Pulse Fitness Studio",
        "industry": "Gyms and fitness",
        "location": "Koramangala, Bengaluru",
        "employees": 9,
        "source": "instagram",
        "requirement": (
            "Trial enquiries come on Instagram DMs and get lost. Wants one enquiry list. "
        ),
        "age_days": 3.4,
        "responded_after_hours": None,
        "status": "new",
        "owner": None,
        "score": None,
    },
    {
        "key": "farhan-interiors",
        "first_name": "Farhan",
        "last_name": "Qureshi",
        "email": "farhan@nestcraftinteriors.in",
        "phone": "+919845012203",
        "company": "NestCraft Interiors",
        "industry": "Interior design",
        "location": "Whitefield, Bengaluru",
        "employees": 22,
        "source": "referral",
        "requirement": (
            "Site-visit enquiries tracked on a shared sheet. Two designers duplicate calls. "
        ),
        "age_days": 5.8,
        "responded_after_hours": None,
        "status": "new",
        "owner": None,
        "score": None,
    },
    # --- worked prospects, owned, with history --------------------------------
    {
        "key": "anitha-coaching",
        "first_name": "Anitha",
        "last_name": "Reddy",
        "email": "anitha@vidyapeethacademy.in",
        "phone": "+919845012204",
        "company": "Vidyapeeth Academy",
        "industry": "Coaching institutes",
        "location": "Jayanagar, Bengaluru",
        "employees": 31,
        "source": "google_ads",
        "requirement": "Admission enquiries in three notebooks. Wants counsellor-wise ownership.",
        "age_days": 11.0,
        "responded_after_hours": 2.5,
        "status": "qualified",
        "owner": "priya@sangam.co.in",
        "score": 82,
        "category": "hot",
    },
    {
        "key": "vikram-logistics",
        "first_name": "Vikram",
        "last_name": "Shetty",
        "email": "vikram@sahyadrilogistics.in",
        "phone": "+919845012205",
        "company": "Sahyadri Logistics",
        "industry": "Transport and logistics",
        "location": "Peenya, Bengaluru",
        "employees": 48,
        "source": "referral",
        "requirement": "Freight quotes over WhatsApp, no record of who quoted what.",
        "age_days": 17.0,
        "responded_after_hours": 1.0,
        "status": "qualified",
        "owner": "priya@sangam.co.in",
        "score": 76,
        "category": "hot",
    },
    {
        "key": "deepa-salon",
        "first_name": "Deepa",
        "last_name": "Krishnan",
        "email": "deepa@auraSalonspa.in",
        "phone": "+919845012206",
        "company": "Aura Salon & Spa",
        "industry": "Salons and spas",
        "location": "HSR Layout, Bengaluru",
        "employees": 17,
        "source": "web_form",
        "requirement": (
            "Walk-in regulars not recognised by new staff. Wants customer history at the desk."
        ),
        "age_days": 9.0,
        "responded_after_hours": 4.0,
        "status": "contacted",
        "owner": "kiran@sangam.co.in",
        "score": 61,
        "category": "warm",
    },
    {
        "key": "ganesh-hardware",
        "first_name": "Ganesh",
        "last_name": "Kulkarni",
        "email": "ganesh@srinivasahardware.in",
        "phone": "+919845012207",
        "company": "Srinivasa Hardware & Tools",
        "industry": "Retail and distribution",
        "location": "Chickpet, Bengaluru",
        "employees": 12,
        "source": "walk_in",
        "requirement": "Wants to stop losing repeat-order customers to the shop next door.",
        "age_days": 21.0,
        "responded_after_hours": 26.0,
        "status": "nurturing",
        "owner": "kiran@sangam.co.in",
        "score": 44,
        "category": "warm",
    },
    {
        "key": "meenakshi-catering",
        "first_name": "Meenakshi",
        "last_name": "Iyengar",
        "email": "meenakshi@annapurnacaterers.in",
        "phone": "+919845012208",
        "company": "Annapurna Caterers",
        "industry": "Catering and events",
        "location": "Rajajinagar, Bengaluru",
        "employees": 26,
        "source": "whatsapp",
        "requirement": "Event enquiries peak in wedding season and get forgotten by Monday.",
        "age_days": 14.0,
        "responded_after_hours": 3.0,
        "status": "contacted",
        "owner": "priya@sangam.co.in",
        "score": 58,
        "category": "warm",
    },
    {
        "key": "arjun-solar",
        "first_name": "Arjun",
        "last_name": "Patil",
        "email": "arjun@suryatechsolar.in",
        "phone": "+919845012209",
        "company": "SuryaTech Solar Solutions",
        "industry": "Solar and electrical",
        "location": "Yelahanka, Bengaluru",
        "employees": 35,
        "source": "google_ads",
        "requirement": (
            "Site survey requests arrive faster than the two-person office can call back. "
        ),
        "age_days": 8.0,
        "responded_after_hours": 6.5,
        "status": "contacted",
        "owner": "kiran@sangam.co.in",
        "score": 69,
        "category": "warm",
    },
    {
        "key": "nandini-pharma",
        "first_name": "Nandini",
        "last_name": "Rao",
        "email": "nandini@medipointpharmacy.in",
        "phone": "+919845012210",
        "company": "MediPoint Pharmacy Chain",
        "industry": "Pharmacy retail",
        "location": "Malleshwaram, Bengaluru",
        "employees": 41,
        "source": "referral",
        "requirement": "Refill reminders done manually by one person who is leaving.",
        "age_days": 26.0,
        "responded_after_hours": 2.0,
        "status": "nurturing",
        "owner": "priya@sangam.co.in",
        "score": 51,
        "category": "warm",
    },
    # --- the duplicate nobody merged -----------------------------------------
    {
        "key": "farhan-dup",
        "first_name": "Farhan",
        "last_name": None,
        "email": None,
        "phone": "+919845012203",
        "company": "Nestcraft Interior Designs",
        "industry": "Interior design",
        "location": "Bengaluru",
        "employees": None,
        "source": "webchat",
        "requirement": "Asked the same question on the website chat four days after the referral.",
        "age_days": 1.6,
        "responded_after_hours": None,
        "status": "new",
        "owner": None,
        "score": None,
    },
    # --- disqualified, with the reason kept -----------------------------------
    {
        "key": "sameer-startup",
        "first_name": "Sameer",
        "last_name": "Ghosh",
        "email": "sameer@quickcartlabs.io",
        "phone": "+919845012211",
        "company": "QuickCart Labs",
        "industry": "Software startup",
        "location": "Bellandur, Bengaluru",
        "employees": 4,
        "source": "web_form",
        "requirement": "Wanted a custom ERP build. Outside what Sangam does.",
        "age_days": 19.0,
        "responded_after_hours": 5.0,
        "status": "disqualified",
        "owner": "priya@sangam.co.in",
        "score": 18,
        "category": "cold",
        "disqualify_reason": "Wants a bespoke ERP build; not our product and not our price band.",
    },
    # --- converted: these become contacts, accounts and deals ------------------
    {
        "key": "lakshmi-clinic",
        "first_name": "Lakshmi",
        "last_name": "Venkatesh",
        "email": "lakshmi@sanjeevaniclinics.in",
        "phone": "+919845012212",
        "company": "Sanjeevani Multi-speciality Clinics",
        "industry": "Clinics and diagnostics",
        "location": "Basavanagudi, Bengaluru",
        "employees": 55,
        "source": "referral",
        "requirement": "Four branches, one reception queue, no shared patient enquiry history.",
        "age_days": 38.0,
        "responded_after_hours": 1.5,
        "status": "converted",
        "owner": "priya@sangam.co.in",
        "score": 88,
        "category": "hot",
    },
    {
        "key": "imran-realty",
        "first_name": "Imran",
        "last_name": "Sheikh",
        "email": "imran@greenfieldrealty.in",
        "phone": "+919845012213",
        "company": "Greenfield Realty Partners",
        "industry": "Real estate",
        "location": "Sarjapur Road, Bengaluru",
        "employees": 19,
        "source": "google_ads",
        "requirement": "Site-visit leads from three portals, no single owner per enquiry.",
        "age_days": 44.0,
        "responded_after_hours": 3.5,
        "status": "converted",
        "owner": "kiran@sangam.co.in",
        "score": 79,
        "category": "hot",
    },
    {
        "key": "priyanka-boutique",
        "first_name": "Priyanka",
        "last_name": "Desai",
        "email": "priyanka@zariboutique.in",
        "phone": "+919845012214",
        "company": "Zari Boutique",
        "industry": "Apparel retail",
        "location": "Jayanagar, Bengaluru",
        "employees": 8,
        "source": "instagram",
        "requirement": "Custom-order enquiries on Instagram, measurements lost between staff.",
        "age_days": 31.0,
        "responded_after_hours": 8.0,
        "status": "converted",
        "owner": "kiran@sangam.co.in",
        "score": 64,
        "category": "warm",
    },
)

# --- accounts and deals for the converted prospects ---------------------------

ACCOUNTS: tuple[dict[str, Any], ...] = (
    {
        "key": "sanjeevani",
        "name": "Sanjeevani Multi-speciality Clinics",
        "industry": "Clinics and diagnostics",
        "website": "https://sanjeevaniclinics.in",
        "phone": "+918041202212",
        "employees": 55,
        "owner": "priya@sangam.co.in",
        "contact_key": "lakshmi-clinic",
    },
    {
        "key": "greenfield",
        "name": "Greenfield Realty Partners",
        "industry": "Real estate",
        "website": "https://greenfieldrealty.in",
        "phone": "+918041202213",
        "employees": 19,
        "owner": "kiran@sangam.co.in",
        "contact_key": "imran-realty",
    },
    {
        "key": "zari",
        "name": "Zari Boutique",
        "industry": "Apparel retail",
        "website": "https://zariboutique.in",
        "phone": "+918041202214",
        "employees": 8,
        "owner": "kiran@sangam.co.in",
        "contact_key": "priyanka-boutique",
    },
)

# amount_minor is paise, so a 24 lakh rupee contract is 24_00_000_00 - the last
# two digits are the paise. Writing the rupee figure here would understate every
# deal by a factor of a hundred, which is exactly what it did the first time.
DEALS: tuple[dict[str, Any], ...] = (
    {
        "key": "sanjeevani-deal",
        "title": "Sanjeevani - front desk and follow-up rollout",
        "account": "sanjeevani",
        "contact": "lakshmi-clinic",
        "stage": "Negotiation",
        "amount_minor": 24_00_000_00,
        "owner": "priya@sangam.co.in",
        "close_in_days": 9,
        "status": "open",
    },
    {
        "key": "greenfield-deal",
        "title": "Greenfield Realty - enquiry ownership pilot",
        "account": "greenfield",
        "contact": "imran-realty",
        "stage": "Proposal",
        "amount_minor": 15_00_000_00,
        "owner": "kiran@sangam.co.in",
        "close_in_days": 16,
        "status": "open",
    },
    {
        "key": "zari-deal",
        "title": "Zari Boutique - custom order tracking",
        "account": "zari",
        "contact": "priyanka-boutique",
        "stage": "Won",
        "amount_minor": 6_60_000_00,
        "owner": "kiran@sangam.co.in",
        "close_in_days": -6,
        "status": "won",
    },
    {
        "key": "vidyapeeth-deal",
        "title": "Vidyapeeth Academy - admission enquiry desk",
        "account": None,
        "contact": None,
        "stage": "Qualified",
        "amount_minor": 12_00_000_00,
        "owner": "priya@sangam.co.in",
        "close_in_days": 24,
        "status": "open",
    },
    {
        "key": "sahyadri-deal",
        "title": "Sahyadri Logistics - quote trail on WhatsApp",
        "account": None,
        "contact": None,
        "stage": "Qualified",
        "amount_minor": 9_00_000_00,
        "owner": "priya@sangam.co.in",
        "close_in_days": 30,
        "status": "open",
    },
    {
        "key": "lost-deal",
        "title": "Ravi Enterprises - enquiry tracking",
        "account": None,
        "contact": None,
        "stage": "Lost",
        "amount_minor": 4_80_000_00,
        "owner": "kiran@sangam.co.in",
        "close_in_days": -13,
        "status": "lost",
        "loss_reason": "Chose a cheaper spreadsheet-based tool. Revisit after their next season.",
    },
)

# --- follow-ups ---------------------------------------------------------------
#
# `due_in_hours` is signed: negative is overdue. The two overdue rows and the two
# due-today rows are the ones the operational dashboard has to count correctly.

FOLLOW_UPS: tuple[dict[str, Any], ...] = (
    {
        "title": "Call Ganesh back about the repeat-order list",
        "lead": "ganesh-hardware",
        "owner": "kiran@sangam.co.in",
        "due_in_hours": -54,
        "priority": "high",
        "next_action": True,
        "description": "Promised a callback after his stock-taking week. Two weeks quiet since.",
    },
    {
        "title": "Send Meenakshi the wedding-season enquiry plan",
        "lead": "meenakshi-catering",
        "owner": "priya@sangam.co.in",
        "due_in_hours": -19,
        "priority": "high",
        "next_action": True,
        "description": (
            "She asked for it in writing before speaking to her brother, who is the co-owner. "
        ),
    },
    {
        "title": "Confirm demo slot with Anitha's counsellor team",
        "lead": "anitha-coaching",
        "owner": "priya@sangam.co.in",
        "due_in_hours": 5,
        "priority": "urgent",
        "next_action": True,
        "description": (
            "Three counsellors need to be in the room; she can only do before admissions open."
        ),
    },
    {
        "title": "Follow up on Arjun's site-survey backlog numbers",
        "lead": "arjun-solar",
        "owner": "kiran@sangam.co.in",
        "due_in_hours": 8,
        "priority": "normal",
        "next_action": True,
        "description": "He was pulling the count of missed callbacks from last month.",
    },
    {
        "title": "Second call with Vikram on quote history",
        "lead": "vikram-logistics",
        "owner": "priya@sangam.co.in",
        "due_in_hours": 30,
        "priority": "normal",
        "next_action": True,
    },
    {
        "title": "Check whether Deepa's front-desk staff can attend a walkthrough",
        "lead": "deepa-salon",
        "owner": "kiran@sangam.co.in",
        "due_in_hours": 52,
        "priority": "normal",
        "next_action": True,
    },
    {
        "title": "Share refill-reminder example with Nandini",
        "lead": "nandini-pharma",
        "owner": "priya@sangam.co.in",
        "due_in_hours": 76,
        "priority": "low",
        "next_action": False,
    },
    {
        "title": "Send Vidyapeeth the revised proposal",
        "deal": "vidyapeeth-deal",
        "owner": "priya@sangam.co.in",
        "due_in_hours": 27,
        "priority": "high",
        "next_action": True,
    },
    {
        "title": "Negotiation call with Sanjeevani finance",
        "deal": "sanjeevani-deal",
        "owner": "priya@sangam.co.in",
        "due_in_hours": 22,
        "priority": "urgent",
        "next_action": True,
    },
    # Completed work, so "closed on time" is answerable rather than inferred.
    {
        "title": "First call with Lakshmi at Sanjeevani",
        "lead": "lakshmi-clinic",
        "owner": "priya@sangam.co.in",
        "due_in_hours": -720,
        "priority": "high",
        "next_action": False,
        "completed_hours_ago": 700,
    },
    {
        "title": "Send Imran the pilot scope",
        "lead": "imran-realty",
        "owner": "kiran@sangam.co.in",
        "due_in_hours": -480,
        "priority": "normal",
        "next_action": False,
        "completed_hours_ago": 470,
    },
)

# --- what was actually said ---------------------------------------------------
#
# Activity rows are the shared memory the whole product is arranged around. These
# are written against the *lead*, which is why they survive conversion.

CONVERSATIONS: tuple[dict[str, Any], ...] = (
    {
        "lead": "anitha-coaching",
        "type": "call",
        "subject": "Discovery call - admission enquiry handling",
        "body": (
            "Three counsellors take enquiries into separate notebooks. Nobody knows which "
            "parent was already called. Admissions open in six weeks, so the timing is real. "
            "Decision is hers; her husband handles the accounts."
        ),
        "actor": "priya@sangam.co.in",
        "hours_ago": 220,
    },
    {
        "lead": "anitha-coaching",
        "type": "whatsapp",
        "subject": "Sent the two-page summary",
        "body": (
            "Shared what we discussed plus the counsellor-ownership example. She read it same "
            "evening."
        ),
        "actor": "priya@sangam.co.in",
        "hours_ago": 190,
    },
    {
        "lead": "anitha-coaching",
        "type": "meeting",
        "subject": "Walkthrough with Anitha and one counsellor",
        "body": (
            "Showed the enquiry list and the follow-up queue. Her question was whether "
            "a counsellor can see another counsellor's parent. Answered: only if the "
            "manager allows it."
        ),
        "actor": "priya@sangam.co.in",
        "hours_ago": 96,
    },
    {
        "lead": "vikram-logistics",
        "type": "call",
        "subject": "Quote trail problem",
        "body": (
            "Four staff quote freight over WhatsApp from personal phones. When one left in March "
            "the quote history left with him. That is the pain he leads with."
        ),
        "actor": "priya@sangam.co.in",
        "hours_ago": 300,
    },
    {
        "lead": "vikram-logistics",
        "type": "email",
        "subject": "Sent indicative pricing",
        "body": "Annual, two branches, five users. He asked for a month-by-month option.",
        "actor": "priya@sangam.co.in",
        "hours_ago": 150,
    },
    {
        "lead": "ganesh-hardware",
        "type": "call",
        "subject": "First call - repeat orders",
        "body": (
            "Counter staff recognise regulars by face, not by record. Loses orders when the "
            "regular staff member is off. Asked to be called back after stock-taking."
        ),
        "actor": "kiran@sangam.co.in",
        "hours_ago": 400,
    },
    {
        "lead": "deepa-salon",
        "type": "call",
        "subject": "Front desk context",
        "body": (
            "New receptionists do not know which customer prefers which stylist. She has written "
            "it in a diary that is now full."
        ),
        "actor": "kiran@sangam.co.in",
        "hours_ago": 170,
    },
    {
        "lead": "arjun-solar",
        "type": "call",
        "subject": "Site survey backlog",
        "body": (
            "Two people answering, roughly forty enquiries a week in summer. Callbacks slip "
            "by days."
        ),
        "actor": "kiran@sangam.co.in",
        "hours_ago": 130,
    },
    {
        "lead": "meenakshi-catering",
        "type": "whatsapp",
        "subject": "Wedding season enquiries",
        "body": "Peak is Nov-Feb. Enquiries arrive on Saturday and are forgotten by Monday.",
        "actor": "priya@sangam.co.in",
        "hours_ago": 260,
    },
    {
        "lead": "nandini-pharma",
        "type": "call",
        "subject": "Refill reminders",
        "body": (
            "One staff member does refill reminders from memory and is leaving in two months. "
            "That deadline is the reason this is not a someday project."
        ),
        "actor": "priya@sangam.co.in",
        "hours_ago": 520,
    },
    {
        "lead": "lakshmi-clinic",
        "type": "meeting",
        "subject": "Branch managers walkthrough",
        "body": (
            "All four branch managers attended. Agreed to start with the Basavanagudi desk only."
        ),
        "actor": "priya@sangam.co.in",
        "hours_ago": 300,
    },
    {
        "lead": "sameer-startup",
        "type": "call",
        "subject": "Scoping call",
        "body": (
            "Wanted stock, invoicing and payroll in one build. Told him plainly this is not "
            "what we do."
        ),
        "actor": "priya@sangam.co.in",
        "hours_ago": 430,
    },
)

NOTES: tuple[dict[str, Any], ...] = (
    {
        "lead": "anitha-coaching",
        "body": "Best reached between 11am and 1pm. Do not call during evening batches.",
        "actor": "priya@sangam.co.in",
        "pinned": True,
        "hours_ago": 210,
    },
    {
        "lead": "vikram-logistics",
        "body": "Price-sensitive. Comparing against a free tool his nephew set up.",
        "actor": "priya@sangam.co.in",
        "pinned": True,
        "hours_ago": 140,
    },
    {
        "lead": "ganesh-hardware",
        "body": "Shop shuts on Wednesdays. Calling on a Wednesday is a wasted call.",
        "actor": "kiran@sangam.co.in",
        "pinned": True,
        "hours_ago": 380,
    },
    {
        "lead": "deepa-salon",
        "body": "Wants to see it working at another salon before committing.",
        "actor": "kiran@sangam.co.in",
        "pinned": False,
        "hours_ago": 160,
    },
)


def resolve_password() -> tuple[str, bool]:
    supplied = os.environ.get("DEMO_PASSWORD")
    if supplied:
        check = validate_password(supplied)
        if not check.ok:
            raise SystemExit("DEMO_PASSWORD rejected: " + "; ".join(check.problems))
        return supplied, False
    return f"sangam-{secrets.token_urlsafe(24)}", True


def _spec(
    *,
    tenant_id: UUID,
    name: str,
    slug: str,
    team: tuple[tuple[str, str, Role, str], ...],
    kind: str,
) -> WorkspaceSpec:
    """This script's terse team tuples, in the shared provisioning vocabulary."""
    return WorkspaceSpec(
        tenant_id=tenant_id,
        name=name,
        slug=slug,
        kind=kind,
        people=tuple(
            Person(email=email, full_name=full_name, role=role, scope=scope)
            for email, full_name, role, scope in team
        ),
        branch_name="Bengaluru",
    )


async def ensure_workspace(
    password_hash: str, *, reset_passwords: bool = False
) -> tuple[dict[str, UUID], int]:
    """The founders' workspace, plus the empty one the browser tests write to.

    The tenant, role, user, branch and team routines this used to carry live in
    `application.tenants.provisioning` now, because a pilot needs exactly the same
    ones and a second copy is how a workspace ends up with managers and no team -
    the defect the founders hit in session 4.

    **Existing people keep their passwords.** This used to rewrite the hash of
    every seeded account on every run, so starting the stack without
    `DEMO_PASSWORD` minted a fresh random password and silently locked the
    founders out of their own workspace - which is exactly what happened. A first
    seed may create credentials; a later start must not rotate them. Rotation is
    now something somebody asks for by name, with `--reset-passwords`.
    """
    created = 0
    async with admin_session() as session:
        result = await provision_workspace(
            session,
            _spec(
                tenant_id=SANGAM_ID,
                name="Sangam",
                slug="sangam",
                team=TEAM,
                kind=FOUNDER,
            ),
            password_hash=password_hash,
            reset_credentials=reset_passwords,
        )
        created += len(result.created_users)
        e2e = await provision_workspace(
            session,
            _spec(
                tenant_id=SANGAM_E2E_ID,
                name="Sangam Test Workspace",
                slug="sangam-e2e",
                team=E2E_TEAM,
                kind=TEST,
            ),
            password_hash=password_hash,
            reset_credentials=reset_passwords,
        )
        created += len(e2e.created_users)
        pilot = await provision_workspace(
            session,
            _spec(
                tenant_id=SANGAM_PILOT_E2E_ID,
                name="Pilot Test Workspace",
                slug="sangam-pilot-e2e",
                team=PILOT_E2E_TEAM,
                kind=TEST,
            ),
            password_hash=password_hash,
            reset_credentials=reset_passwords,
        )
        created += len(pilot.created_users)

    return result.users, created


async def refresh() -> None:
    """Delete only the rows a previous demo seed recorded creating.

    This used to be `DELETE FROM app.leads WHERE tenant_id = :t` and the rest of
    the tables the same way - every row in the workspace, on the assumption that a
    demo tenant holds only demo data. Once the founders started prospecting for
    real out of this same workspace that assumption was false, and it destroyed a
    prospect they had created and worked, together with its notes and tasks.

    It now deletes strictly what `application.tenants.demo_data` recorded the seed
    creating. A founder-created or imported record was never in the manifest, so
    it is not a candidate for deletion - preserved by construction rather than by
    being correctly recognised as real.

    `app.activities`, `app.lead_source_events` and the audit log are absent from
    the manifest entirely: they are append-only, the database refuses to delete
    from them, and that refusal is exactly why the evidence of the lost prospect
    survived to be recovered.
    """
    from application.tenants.demo_data import delete_recorded_rows
    from scripts.backup_local import take_snapshot

    # Before anything is deleted, and fatal if it fails. A refresh is now narrow
    # enough that it should not be able to lose real data, but "should not" is
    # what the previous version also believed.
    snapshot = take_snapshot("demo-refresh")
    logger.info("refresh_snapshot_taken", file=snapshot.name)

    async with admin_session() as session:
        removed = await delete_recorded_rows(session, SANGAM_ID)
    logger.info("sangam_refreshed", **removed)


async def _ensure_pipeline(session: Any) -> dict[str, UUID]:
    """The default sales ladder, created here so deals can be seeded directly."""
    from application.crm.deals import DEFAULT_PIPELINE_NAME, DEFAULT_STAGES

    pipeline = (
        (await session.execute(select(Pipeline).where(Pipeline.deleted_at.is_(None))))
        .scalars()
        .first()
    )
    if pipeline is None:
        pipeline_id = uuid7()
        session.add(
            Pipeline(
                id=pipeline_id,
                tenant_id=SANGAM_ID,
                entity_type="deal",
                name=DEFAULT_PIPELINE_NAME,
                is_default=True,
                is_active=True,
                version=1,
            )
        )
        await session.flush()
    else:
        pipeline_id = pipeline.id

    stages: dict[str, UUID] = {}
    for spec in DEFAULT_STAGES:
        found = (
            await session.execute(
                select(Stage.id).where(Stage.pipeline_id == pipeline_id, Stage.name == spec["name"])
            )
        ).scalar_one_or_none()
        if found:
            stages[spec["name"]] = UUID(str(found))
            continue
        stage_id = uuid7()
        session.add(
            Stage(
                id=stage_id,
                tenant_id=SANGAM_ID,
                pipeline_id=pipeline_id,
                name=spec["name"],
                position=spec["position"],
                probability=spec["probability"],
                is_won=bool(spec.get("is_won", False)),
                is_lost=bool(spec.get("is_lost", False)),
                version=1,
            )
        )
        stages[spec["name"]] = stage_id
    await session.flush()
    return {"pipeline": pipeline_id, **stages}


async def seed_business(users: dict[str, UUID]) -> dict[str, int]:
    """Prospects, history, follow-ups and pipeline, all under the tenant's own context."""
    now = utcnow()
    counts = {"leads": 0, "activities": 0, "notes": 0, "tasks": 0, "deals": 0, "contacts": 0}
    # Everything this run creates, so a later refresh can delete exactly this and
    # nothing else. See `application.tenants.demo_data` for why the alternative -
    # deleting by tenant - destroyed a real founder record.
    manifest = empty_manifest()

    async with tenant_session(SANGAM_ID) as session:
        # Whether the *samples* are already present, not whether the workspace has
        # any leads at all. Checking for any lead meant that one recovered founder
        # prospect was enough to stop the sample set ever being rebuilt.
        from application.tenants.demo_data import load_manifest

        already = await load_manifest(session, SANGAM_ID)
        if already.get("leads"):
            logger.info("sangam_already_seeded", samples=len(already["leads"]))
            return counts

        ids = await _ensure_pipeline(session)

        # Every seeded prospect belongs to the Sales team, so a team-scoped
        # manager sees the same book the owner does. Without this the records
        # exist but are invisible to exactly the person meant to run them.
        sales_team_id = (
            await session.execute(select(Team.id).where(Team.name == "Sales"))
        ).scalar_one_or_none()

        # --- prospects -------------------------------------------------------
        lead_ids: dict[str, UUID] = {}
        for row in PROSPECTS:
            lead_id = uuid7()
            lead_ids[row["key"]] = lead_id
            manifest["leads"].append(str(lead_id))
            created = now - _days(row["age_days"])
            responded = (
                None
                if row["responded_after_hours"] is None
                else created + _hours(row["responded_after_hours"])
            )
            session.add(
                Lead(
                    id=lead_id,
                    tenant_id=SANGAM_ID,
                    first_name=row["first_name"],
                    last_name=row["last_name"],
                    email=row["email"],
                    phone=row["phone"],
                    source=row["source"],
                    source_channel="web",
                    capture={
                        # Marks this as one of the invented demonstration
                        # businesses. Once the founders start entering real
                        # prospects into this same workspace, the two need to be
                        # tellable apart at a glance - and a flag on the record
                        # itself beats a separate tenant nobody remembers to
                        # switch to.
                        "demo_data": True,
                        "company": row["company"],
                        "industry": row["industry"],
                        "location": row["location"],
                        "employees": row["employees"],
                        "requirement": row["requirement"],
                    },
                    utm={},
                    qualification_score=row.get("score"),
                    category=row.get("category"),
                    qualified_by="manual" if row.get("score") is not None else None,
                    qualified_at=created + _hours(24) if row.get("score") is not None else None,
                    status=row["status"],
                    disqualify_reason=row.get("disqualify_reason"),
                    assignee_id=users.get(row["owner"]) if row["owner"] else None,
                    team_id=sales_team_id,
                    dedupe_key=f"p:{row['phone']}",
                    first_response_at=responded,
                    created_at=created,
                    updated_at=created,
                    version=1,
                )
            )
            counts["leads"] += 1

            # Every seeded first response is backed by the outbound activity that
            # justifies it, written at exactly that moment. Otherwise the demo
            # would show a "time to first response" with no call behind it, which
            # is precisely the kind of unbacked number this workspace exists to
            # let the founders stop trusting.
            if responded is not None:
                channel = "whatsapp" if row["source"] == "whatsapp" else "call"
                session.add(
                    Activity(
                        id=uuid7(),
                        tenant_id=SANGAM_ID,
                        activity_type=channel,
                        subject=f"First contact with {row['first_name']}",
                        body=("Got back to the enquiry and confirmed what they are trying to fix."),
                        entity_type="lead",
                        entity_id=lead_id,
                        actor_id=users.get(row["owner"]) if row["owner"] else None,
                        actor_type="user",
                        metadata_json={"direction": "outbound"},
                        created_at=responded,
                        updated_at=responded,
                    )
                )
                counts["activities"] += 1
        await session.flush()

        # The duplicate is recorded, not silently merged: a human decides.
        candidate_id = uuid7()
        manifest["lead_duplicate_candidates"].append(str(candidate_id))
        session.add(
            LeadDuplicateCandidate(
                id=candidate_id,
                tenant_id=SANGAM_ID,
                lead_id=lead_ids["farhan-dup"],
                candidate_lead_id=lead_ids["farhan-interiors"],
                match_reason="phone_exact",
                confidence=0.95,
                resolution="pending",
            )
        )

        # --- accounts and contacts for the converted prospects ----------------
        account_ids: dict[str, UUID] = {}
        contact_ids: dict[str, UUID] = {}
        for acc in ACCOUNTS:
            account_id = uuid7()
            account_ids[acc["key"]] = account_id
            manifest["accounts"].append(str(account_id))
            session.add(
                Account(
                    id=account_id,
                    tenant_id=SANGAM_ID,
                    name=acc["name"],
                    industry=acc["industry"],
                    website=acc["website"],
                    phone=acc["phone"],
                    employee_count=acc["employees"],
                    owner_id=users[acc["owner"]],
                    address={"city": "Bengaluru", "state": "Karnataka", "country": "IN"},
                    custom_fields={"demo_data": True},
                    version=1,
                )
            )

            source = next(p for p in PROSPECTS if p["key"] == acc["contact_key"])
            contact_id = uuid7()
            contact_ids[acc["contact_key"]] = contact_id
            manifest["contacts"].append(str(contact_id))
            session.add(
                Contact(
                    id=contact_id,
                    tenant_id=SANGAM_ID,
                    first_name=source["first_name"],
                    last_name=source["last_name"],
                    email=source["email"],
                    phone=source["phone"],
                    company=source["company"],
                    title="Owner",
                    status="active",
                    source=source["source"],
                    address={"city": "Bengaluru", "state": "Karnataka", "country": "IN"},
                    custom_fields={"demo_data": True, "requirement": source["requirement"]},
                    tags=[],
                    assignee_id=users[acc["owner"]],
                    account_id=account_id,
                    dedupe_key=f"e:{source['email']}",
                    last_contact_at=now - _days(4),
                    version=1,
                )
            )
            counts["contacts"] += 1
        await session.flush()

        # Link the converted lead back to what it became, so the history is one chain.
        for acc in ACCOUNTS:
            key = acc["contact_key"]
            lead = await session.get(Lead, lead_ids[key])
            if lead is not None:
                lead.converted_contact_id = contact_ids[key]
                lead.converted_at = now - _days(6)

        # --- deals ------------------------------------------------------------
        deal_ids: dict[str, UUID] = {}
        for deal in DEALS:
            deal_id = uuid7()
            deal_ids[deal["key"]] = deal_id
            manifest["deals"].append(str(deal_id))
            stage_id = ids[deal["stage"]]
            closed = deal["status"] in ("won", "lost")
            session.add(
                Deal(
                    id=deal_id,
                    tenant_id=SANGAM_ID,
                    contact_id=contact_ids.get(deal["contact"]) if deal["contact"] else None,
                    account_id=account_ids.get(deal["account"]) if deal["account"] else None,
                    pipeline_id=ids["pipeline"],
                    stage_id=stage_id,
                    title=deal["title"],
                    amount_minor=deal["amount_minor"],
                    currency="INR",
                    probability={
                        "New": 10,
                        "Qualified": 30,
                        "Proposal": 60,
                        "Negotiation": 80,
                        "Won": 100,
                        "Lost": 0,
                    }[deal["stage"]],
                    status=deal["status"],
                    loss_reason=deal.get("loss_reason"),
                    expected_close_date=now + _days(deal["close_in_days"]),
                    closed_at=now + _days(deal["close_in_days"]) if closed else None,
                    assignee_id=users[deal["owner"]],
                    custom_fields={"demo_data": True},
                    source_lead_id=lead_ids.get(deal["contact"]) if deal["contact"] else None,
                    version=1,
                )
            )
            counts["deals"] += 1
        await session.flush()

        # --- what was said ----------------------------------------------------
        for entry in CONVERSATIONS:
            when = now - _hours(entry["hours_ago"])
            session.add(
                Activity(
                    id=uuid7(),
                    tenant_id=SANGAM_ID,
                    activity_type=entry["type"],
                    subject=entry["subject"],
                    body=entry["body"],
                    entity_type="lead",
                    entity_id=lead_ids[entry["lead"]],
                    actor_id=users[entry["actor"]],
                    actor_type="user",
                    # These are all the business reaching out; recorded as such so
                    # the timeline and the first-response rule read the same field.
                    metadata_json={"direction": "outbound"},
                    created_at=when,
                    updated_at=when,
                )
            )
            counts["activities"] += 1

        for entry in NOTES:
            when = now - _hours(entry["hours_ago"])
            note_id = uuid7()
            manifest["notes"].append(str(note_id))
            session.add(
                Note(
                    id=note_id,
                    tenant_id=SANGAM_ID,
                    entity_type="lead",
                    entity_id=lead_ids[entry["lead"]],
                    body=entry["body"],
                    is_pinned=entry["pinned"],
                    created_by=users[entry["actor"]],
                    created_at=when,
                    updated_at=when,
                    version=1,
                )
            )
            counts["notes"] += 1

        # --- follow-ups -------------------------------------------------------
        for item in FOLLOW_UPS:
            completed_hours = item.get("completed_hours_ago")
            if "lead" in item:
                entity_type, entity_id = "lead", lead_ids[item["lead"]]
            else:
                entity_type, entity_id = "deal", deal_ids[item["deal"]]
            task_id = uuid7()
            manifest["tasks"].append(str(task_id))
            session.add(
                Task(
                    id=task_id,
                    tenant_id=SANGAM_ID,
                    title=item["title"],
                    description=item.get("description"),
                    entity_type=entity_type,
                    entity_id=entity_id,
                    assignee_id=users[item["owner"]],
                    due_at=now + _hours(item["due_in_hours"]),
                    priority=item["priority"],
                    status="completed" if completed_hours else "open",
                    completed_at=now - _hours(completed_hours) if completed_hours else None,
                    is_next_action=item["next_action"],
                    source="manual",
                    created_by=users[item["owner"]],
                    version=1,
                )
            )
            counts["tasks"] += 1

        # Written inside the same transaction as the rows it describes, so the
        # manifest can never claim rows that were rolled back.
        await record_manifest(session, SANGAM_ID, manifest)

    return counts


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the Sangam dogfood tenant")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="rebuild the sample rows this seed previously recorded creating",
    )
    parser.add_argument(
        "--adopt-existing-samples",
        action="store_true",
        help=(
            "one-time migration: record the rows an older seed marked as samples so a "
            "refresh can rebuild them. Never adopts unmarked or founder-created records."
        ),
    )
    parser.add_argument(
        "--reset-passwords",
        action="store_true",
        help=(
            "rotate the passwords of people who already exist. Off by default: a "
            "normal start must never lock the founders out of their own workspace."
        ),
    )
    args = parser.parse_args()

    configure_logging(json_output=False)
    settings = get_settings()
    if settings.environment != "local":
        raise SystemExit(f"seed_sangam refuses to run in the '{settings.environment}' environment")

    password, generated = resolve_password()
    users, created = await ensure_workspace(
        hash_password(password), reset_passwords=args.reset_passwords
    )

    if args.adopt_existing_samples:
        from application.tenants.demo_data import adopt_existing_demo_rows

        async with admin_session() as session:
            adopted = await adopt_existing_demo_rows(session, SANGAM_ID)
        counted = {table: len(ids) for table, ids in adopted.items() if ids}
        print(f"\n  Adopted existing sample rows: {counted}\n")  # noqa: T201

    if args.refresh:
        await refresh()
    counts = await seed_business(users)

    print("\n" + "=" * 66)  # noqa: T201
    print("  Sangam dogfood workspace ready")  # noqa: T201
    print("=" * 66)  # noqa: T201
    for email, _name, role, _scope in TEAM:
        print(f"  {email:26} {role.value}")  # noqa: T201
    print("\n  browser tests use a separate, empty workspace:")  # noqa: T201
    print(f"  {E2E_TEAM[0][0]:26} (sangam-e2e)")  # noqa: T201
    # Only claim the printed password works for accounts it was actually applied
    # to. Printing it unconditionally is how somebody ends up certain they know a
    # credential that was never set - and how a normal start silently locked the
    # founders out of their own workspace.
    if args.reset_passwords:
        print(f"\n  password (reset for everyone): {password}")  # noqa: T201
    elif created:
        print(f"\n  password for the {created} new account(s): {password}")  # noqa: T201
        print("  everyone else kept the password they already had.")  # noqa: T201
    else:
        print("\n  passwords: unchanged. Every account here already existed.")  # noqa: T201
        print("  to rotate them deliberately:")  # noqa: T201
        print("    DEMO_PASSWORD='...' python src/scripts/seed_sangam.py --reset-passwords")  # noqa: T201
    if generated and (args.reset_passwords or created):
        print("  (generated for this run only; set DEMO_PASSWORD to choose your own)")  # noqa: T201
    if any(counts.values()):
        print(  # noqa: T201
            f"\n  prospects {counts['leads']}  deals {counts['deals']}  "
            f"follow-ups {counts['tasks']}  history {counts['activities'] + counts['notes']}"
        )
    else:
        print("\n  workspace already holds prospects; nothing was overwritten.")  # noqa: T201
        print("  use --refresh to rebuild the synthetic rows.")  # noqa: T201
    print("=" * 66 + "\n")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
