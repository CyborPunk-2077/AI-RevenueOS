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

from sqlalchemy import select, text

from domain.auth.permissions import ROLE_PERMISSIONS, Role
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
from infrastructure.database.models.tenancy import Tenant
from infrastructure.database.models.users import Role as RoleRow
from infrastructure.database.models.users import RolePermission, User, UserRole
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


async def _ensure_role(session: Any, tenant_id: UUID, role: Role, scope: str) -> UUID:
    existing = (
        await session.execute(
            select(RoleRow.id).where(RoleRow.tenant_id == tenant_id, RoleRow.name == role.value)
        )
    ).scalar_one_or_none()
    if existing:
        return UUID(str(existing))

    role_id = uuid7()
    session.add(
        RoleRow(
            id=role_id,
            tenant_id=tenant_id,
            name=role.value,
            description=f"Sangam {role.value}",
            is_system=True,
            default_scope=scope,
            version=1,
        )
    )
    for code in sorted(ROLE_PERMISSIONS[role]):
        session.add(RolePermission(tenant_id=tenant_id, role_id=role_id, permission_code=code))
    return role_id


async def _ensure_tenant_and_people(
    session: Any,
    *,
    tenant_id: UUID,
    name: str,
    slug: str,
    team: tuple[tuple[str, str, Role, str], ...],
    password_hash: str,
) -> dict[str, UUID]:
    """One workspace and its people. Idempotent; a re-run repairs the credentials."""
    users: dict[str, UUID] = {}

    exists = (
        await session.execute(select(Tenant.id).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if not exists:
        session.add(
            Tenant(
                id=tenant_id,
                name=name,
                slug=slug,
                industry_code="other_sme",
                plan_code="growth",
                status="active",
                timezone="Asia/Kolkata",
                currency="INR",
                locale="en-IN",
                version=1,
            )
        )
        await session.flush()

    for email, full_name, role, scope in team:
        role_id = await _ensure_role(session, tenant_id, role, scope)
        user = (
            await session.execute(
                select(User).where(User.tenant_id == tenant_id, User.email == email)
            )
        ).scalar_one_or_none()
        if user is None:
            user_id = uuid7()
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email=email,
                    full_name=full_name,
                    password_hash=password_hash,
                    password_changed_at=utcnow(),
                    status="active",
                    email_verified_at=utcnow(),
                    is_owner=role is Role.OWNER,
                    timezone="Asia/Kolkata",
                    version=1,
                )
            )
            session.add(UserRole(tenant_id=tenant_id, user_id=user_id, role_id=role_id))
        else:
            # A re-run must leave every printed credential working.
            user.password_hash = password_hash
            user.status = "active"
            user.failed_login_count = 0
            user.locked_until = None
            user.mfa_enabled = False
            user.mfa_secret_encrypted = None
            user.mfa_recovery_codes = []
            user_id = user.id
        users[email] = user_id

    return users


async def ensure_workspace(password_hash: str) -> dict[str, UUID]:
    """The founders' workspace, plus the empty one the browser tests write to."""
    async with admin_session() as session:
        users = await _ensure_tenant_and_people(
            session,
            tenant_id=SANGAM_ID,
            name="Sangam",
            slug="sangam",
            team=TEAM,
            password_hash=password_hash,
        )
        await _ensure_tenant_and_people(
            session,
            tenant_id=SANGAM_E2E_ID,
            name="Sangam Test Workspace",
            slug="sangam-e2e",
            team=E2E_TEAM,
            password_hash=password_hash,
        )

    return users


async def refresh() -> None:
    """Delete this tenant's synthetic operational rows. Never touches another tenant.

    `app.activities` and `app.lead_source_events` are deliberately absent from the
    list. A database trigger makes both append-only, and the correct response to a
    guarantee like that is to work with it, not to disable it for the convenience
    of a seed script. The rows left behind reference leads that no longer exist, so
    nothing renders them; they are dead weight in a local database and nothing
    more. For a genuinely empty slate, `RESET_DEMO.cmd` drops the volume.

    (The source-events line used to be in this list and appeared to work, because
    until imports were used in this tenant there were never any rows to delete.)
    """
    async with admin_session() as session:
        for table in (
            "app.tasks",
            "app.notes",
            "app.deals",
            "app.stages",
            "app.pipelines",
            "app.account_contacts",
            "app.accounts",
            "app.contacts",
            "app.lead_duplicate_candidates",
            "app.leads",
        ):
            # Fixed, in-repo allowlist; no user input reaches this string.
            await session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :t"),  # noqa: S608
                {"t": SANGAM_ID},
            )
    logger.info("sangam_refreshed")


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

    async with tenant_session(SANGAM_ID) as session:
        existing_leads = (await session.execute(select(Lead.id).limit(1))).scalar_one_or_none()
        if existing_leads is not None:
            logger.info("sangam_already_seeded")
            return counts

        ids = await _ensure_pipeline(session)

        # --- prospects -------------------------------------------------------
        lead_ids: dict[str, UUID] = {}
        for row in PROSPECTS:
            lead_id = uuid7()
            lead_ids[row["key"]] = lead_id
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
        session.add(
            LeadDuplicateCandidate(
                id=uuid7(),
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
                    custom_fields={},
                    version=1,
                )
            )

            source = next(p for p in PROSPECTS if p["key"] == acc["contact_key"])
            contact_id = uuid7()
            contact_ids[acc["contact_key"]] = contact_id
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
                    custom_fields={"requirement": source["requirement"]},
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
                    custom_fields={},
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
            session.add(
                Note(
                    id=uuid7(),
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
            session.add(
                Task(
                    id=uuid7(),
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

    return counts


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the Sangam dogfood tenant")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="rebuild the synthetic rows (deletes this tenant's leads, deals and history)",
    )
    args = parser.parse_args()

    configure_logging(json_output=False)
    settings = get_settings()
    if settings.environment != "local":
        raise SystemExit(f"seed_sangam refuses to run in the '{settings.environment}' environment")

    password, generated = resolve_password()
    users = await ensure_workspace(hash_password(password))
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
    print(f"\n  password: {password}")  # noqa: T201
    if generated:
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
