#!/usr/bin/env python3
"""
Unit tests for duplicate guard and application deduplication logic.
"""

import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import engine.db as db_mod
import engine.dedup as dedup_mod
from engine.dedup import (
    ApplicationGuard,
    ats_key,
    check_application,
    company_slug,
    ct_key,
    identity_keys,
    is_trustworthy_company,
    title_slug,
    url_key,
)
from engine.scraper import generate_canonical_hash


class TestDedupUrlAndAtsKeys(unittest.TestCase):
    def test_url_canonicalization(self):
        url1 = "https://www.example.com/jobs/123/?utm_source=linkedin&utm_medium=cpc&ref=xyz"
        url2 = "http://example.com/jobs/123?ref=xyz"
        url3 = "https://example.com/jobs/123/apply"

        k1 = url_key(url1)
        k2 = url_key(url2)
        k3 = url_key(url3)

        self.assertEqual(k1, "example.com/jobs/123")
        self.assertEqual(k2, "example.com/jobs/123")
        self.assertEqual(k3, "example.com/jobs/123")

    def test_ats_key_extraction(self):
        # Greenhouse
        gh_url = "https://boards.greenhouse.io/stripe/jobs/4336266009?gh_src=linkedin"
        self.assertEqual(ats_key(gh_url), "gh:4336266009")

        # Greenhouse embed
        gh_embed = "https://boards.greenhouse.io/embed/job_app?for=company&token=556677"
        self.assertEqual(ats_key(gh_embed), "gh:556677")

        # Ashby
        ashby_url = "https://jobs.ashbyhq.com/bjakcareer/ac327c66-652f-402f-985a-43a2b576dc16"
        self.assertEqual(ats_key(ashby_url), "ashby:ac327c66-652f-402f-985a-43a2b576dc16")

        # Lever
        lever_url = "https://jobs.lever.co/palantir/84d284f1-3ec6-4f40-8b4b-4a55d7870404"
        self.assertEqual(ats_key(lever_url), "lever:84d284f1-3ec6-4f40-8b4b-4a55d7870404")

        # LinkedIn
        li_url = "https://www.linkedin.com/jobs/view/4072619082/?trackingId=abc"
        self.assertEqual(ats_key(li_url), "li:4072619082")

        # Amazon
        amzn_url = "https://www.amazon.jobs/en/jobs/2819201/software-development-engineer"
        self.assertEqual(ats_key(amzn_url), "amzn:2819201")

        # Microsoft
        msft_url = "https://careers.microsoft.com/v2/global/en/home.html?pid=1829031"
        self.assertEqual(ats_key(msft_url), "msft:1829031")


class TestCompanyTitleMatching(unittest.TestCase):
    def test_company_slug_normalization(self):
        self.assertEqual(company_slug("Microsoft Corporation, Inc."), "microsoft")
        self.assertEqual(company_slug("Google LLC"), "google")
        self.assertEqual(company_slug("Bjak Pvt Ltd."), "bjak")

    def test_title_slug_normalization(self):
        self.assertEqual(title_slug("iOS Software Engineer [Remote]"), "iossoftwareengineer")
        self.assertEqual(title_slug("Backend Engineer (Remote - India)"), "backendengineer")
        self.assertEqual(title_slug("Full Stack Developer - India | Remote"), "fullstackdeveloper")

    def test_trustworthy_company_detection(self):
        self.assertTrue(is_trustworthy_company("Stripe", "Software Engineer"))
        self.assertTrue(is_trustworthy_company("Microsoft", "AI Engineer"))

        # Untrustworthy generic names
        self.assertFalse(is_trustworthy_company("Target Company", "Software Engineer"))
        self.assertFalse(is_trustworthy_company("Greenhouse Supported Company", "Software Engineer"))
        self.assertFalse(is_trustworthy_company("Remote Contract", "Software Engineer"))
        self.assertFalse(is_trustworthy_company("Bengaluru", "AI Engineer"))
        self.assertFalse(is_trustworthy_company("AI Engineer", "AI Engineer"))


class TestApplicationGuardFlow(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_jobs.db"

        # Monkeypatch DB_PATH in db_mod and dedup_mod
        self.orig_db_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path

        # Clear SCHEMA_READY cache
        dedup_mod._SCHEMA_READY.clear()

        # Initialize schema
        db_mod.init_db()

    def tearDown(self):
        db_mod.DB_PATH = self.orig_db_path
        dedup_mod._SCHEMA_READY.clear()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_guard_allows_new_job_and_blocks_duplicate(self):
        url = "https://jobs.ashbyhq.com/exampleco/11111111-2222-3333-4444-555555555555"

        # 1. Fresh application should be allowed
        with ApplicationGuard(url=url, company="ExampleCo", title="Software Engineer", submit=False) as guard:
            self.assertTrue(guard.allowed)

        # Insert as APPLIED in jobs db
        conn = db_mod.get_db_connection()
        conn.execute(
            "INSERT INTO jobs (job_id, company, title, url, source, status, applied_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("job_test_001", "ExampleCo", "Software Engineer", url, "test_source", "APPLIED",
             datetime.now().isoformat(), datetime.now().isoformat(), datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

        # Re-check via check_application
        decision = check_application(company="ExampleCo", title="Software Engineer", url=url)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "DUPLICATE")

        # Guard should also block duplicate
        with ApplicationGuard(url=url, company="ExampleCo", title="Software Engineer", submit=False) as guard2:
            self.assertFalse(guard2.allowed)
            self.assertEqual(guard2.reason, "DUPLICATE")

    def test_submit_marker_interception(self):
        url = "https://jobs.lever.co/testco/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        # Run guard and simulate submit marker emission in output
        with ApplicationGuard(url=url, company="TestCo", title="Data Engineer", submit=True) as guard:
            self.assertTrue(guard.allowed)
            guard.observe_output("Some log output...\n[[SUBMIT_CLICK_ATTEMPT]]\nClicked submit button!")
            self.assertTrue(guard.submit_attempted)

        # Check that claim was persisted as SUBMITTED in apply_claims
        conn = db_mod.get_db_connection()
        claim = conn.execute("SELECT state FROM apply_claims WHERE claim_key LIKE 'ats:lever:%'").fetchone()
        conn.close()

        self.assertIsNotNone(claim)
        self.assertEqual(claim["state"], "SUBMITTED")

        # Any subsequent attempt on this posting must be blocked immediately
        with ApplicationGuard(url=url, company="TestCo", title="Data Engineer", submit=True) as second_guard:
            self.assertFalse(second_guard.allowed)
            self.assertEqual(second_guard.reason, "DUPLICATE")
            self.assertIn("submit was already clicked", second_guard.detail)

    def test_delegating_guard_blocks_recent_dispatch(self):
        url = "https://jobs.greenhouse.io/sample/jobs/998877"
        now = datetime.now()

        # Insert job in DISPATCHED state recently (10 mins ago)
        conn = db_mod.get_db_connection()
        conn.execute(
            "INSERT INTO jobs (job_id, company, title, url, source, status, updated_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("job_disp_01", "SampleCo", "AI Engineer", url, "test", "DISPATCHED",
             (now - timedelta(minutes=10)).isoformat(), now.isoformat())
        )
        conn.commit()
        conn.close()

        # check_application with delegating=True must block
        decision = check_application(company="SampleCo", title="AI Engineer", url=url, job_id="job_disp_01", delegating=True)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "IN_PROGRESS")
        self.assertIn("was already dispatched", decision.detail)

    def test_ct_key_window_expiration(self):
        url1 = "https://old-portal.com/job1"
        url2 = "https://new-portal.com/job2"
        now = datetime.now()

        # Job applied 150 days ago (outside 120 day window)
        old_time = (now - timedelta(days=150)).isoformat()
        conn = db_mod.get_db_connection()
        conn.execute(
            "INSERT INTO jobs (job_id, company, title, url, source, status, applied_at, updated_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("job_old_01", "Acme Corp", "Backend Engineer", url1, "test", "APPLIED",
             old_time, old_time, old_time)
        )
        conn.commit()
        conn.close()

        # A new posting with different URL/ATS id for same company + title after 150 days is allowed
        decision = check_application(company="Acme Corp", title="Backend Engineer", url=url2)
        self.assertTrue(decision.allowed)

        # But within 30 days, it must be blocked
        recent_time = (now - timedelta(days=30)).isoformat()
        conn = db_mod.get_db_connection()
        conn.execute(
            "UPDATE jobs SET applied_at = ?, updated_at = ? WHERE job_id = 'job_old_01'",
            (recent_time, recent_time)
        )
        conn.commit()
        conn.close()

        decision2 = check_application(company="Acme Corp", title="Backend Engineer", url=url2)
        self.assertFalse(decision2.allowed)
        self.assertEqual(decision2.reason, "DUPLICATE")
        self.assertIn("same company and title", decision2.detail)

    def test_nested_guards_behavior(self):
        url = "https://jobs.ashbyhq.com/nestco/99999999-8888-7777-6666-555555555555"

        with ApplicationGuard(url=url, company="NestCo", title="Full Stack Developer", submit=True) as outer_guard:
            self.assertTrue(outer_guard.allowed)

            # Nested guard for the same application (e.g. called inside dispatch_application)
            with ApplicationGuard(url=url, company="NestCo", title="Full Stack Developer", submit=True) as inner_guard:
                self.assertTrue(inner_guard.allowed)
                inner_guard.observe_output("[[SUBMIT_CLICK_ATTEMPT]]")
                self.assertTrue(inner_guard.submit_attempted)

            # Outer guard must reflect submit_attempted
            self.assertTrue(outer_guard.submit_attempted)


class TestScraperCollisionResistance(unittest.TestCase):
    def test_canonical_hash_avoids_collisions(self):
        company = "Acme Corp"
        # Two different roles at same company on Himalayas
        job1_url = "https://himalayas.app/companies/acme/jobs/backend-engineer-1"
        job2_url = "https://himalayas.app/companies/acme/jobs/frontend-engineer-2"

        h1 = generate_canonical_hash(company, "Backend Engineer", job1_url)
        h2 = generate_canonical_hash(company, "Frontend Engineer", job2_url)

        id1 = f"him_{re.sub(r'[^a-zA-Z0-9]', '', company.lower())[:8]}_{h1[:8]}"
        id2 = f"him_{re.sub(r'[^a-zA-Z0-9]', '', company.lower())[:8]}_{h2[:8]}"

        self.assertNotEqual(id1, id2)
        self.assertTrue(id1.startswith("him_acmecorp_"))
        self.assertTrue(id2.startswith("him_acmecorp_"))
        # Old bug resulted in "him_acmecorp_https:"
        self.assertNotIn("https", id1)
        self.assertNotIn("https", id2)


if __name__ == "__main__":
    unittest.main()
