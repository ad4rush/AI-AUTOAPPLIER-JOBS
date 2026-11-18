#!/usr/bin/env python3
"""
Unit tests for Company Delegator Memory System.
Guarantees that conversation IDs are 100% persistently reused when a company's role comes up.
"""

import tempfile
import unittest
import shutil
from pathlib import Path

import engine.db as db_mod
import engine.company_delegator_memory as del_mem
from engine.company_delegator_memory import (
    normalize_company_slug,
    save_company_delegator,
    get_company_delegator,
    is_conversation_valid
)


class TestCompanyDelegatorMemory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_jobs.db"

        # Monkeypatch DB_PATH in db_mod and del_mem
        self.orig_db_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path

        # Monkeypatch mock brain dir
        self.mock_brain_dir = Path(self.temp_dir) / "brain"
        self.mock_brain_dir.mkdir(parents=True, exist_ok=True)
        self.orig_brain_dir = del_mem.BRAIN_DIR
        del_mem.BRAIN_DIR = self.mock_brain_dir

        # Initialize schema
        db_mod.init_db()
        del_mem.init_company_delegator_table()

    def tearDown(self):
        db_mod.DB_PATH = self.orig_db_path
        del_mem.BRAIN_DIR = self.orig_brain_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_company_slug_normalization(self):
        self.assertEqual(normalize_company_slug("Microsoft Corporation"), "microsoft")
        self.assertEqual(normalize_company_slug("Microsoft Inc."), "microsoft")
        self.assertEqual(normalize_company_slug("REMOTE: Bjak"), "bjak")
        self.assertEqual(normalize_company_slug("DBS Bank Ltd"), "dbs_bank")

    def test_save_and_reuse_conversation_for_company(self):
        convo_id = "test-convo-uuid-12345"

        # Create dummy conversation directory in brain dir so is_conversation_valid returns True
        (self.mock_brain_dir / convo_id).mkdir(parents=True, exist_ok=True)
        self.assertTrue(is_conversation_valid(convo_id))

        # 1. First opening: Save dedicated delegator for Company A
        save_company_delegator(
            company="Company A Inc.",
            conversation_id=convo_id,
            job_id="job_001",
            role_title="Backend Engineer",
            ats_platform="Greenhouse"
        )

        # 2. Lookup when Company A opening 2 comes up (with slight name variation)
        reused = get_company_delegator("Company A")
        self.assertIsNotNone(reused)
        self.assertEqual(reused["conversation_id"], convo_id)
        self.assertEqual(reused["dispatches_count"], 1)

        # 3. Second opening: Save again -> increments count and preserves conversation ID
        save_company_delegator(
            company="Company A",
            conversation_id=convo_id,
            job_id="job_002",
            role_title="Lead AI Engineer",
            ats_platform="Greenhouse"
        )

        reused_second = get_company_delegator("Company A Corporation")
        self.assertIsNotNone(reused_second)
        self.assertEqual(reused_second["conversation_id"], convo_id)
        self.assertEqual(reused_second["dispatches_count"], 2)
        self.assertEqual(reused_second["last_role_title"], "Lead AI Engineer")

    def test_build_worker_prompt_embeds_procedure_memory(self):
        from engine.agent_delegator import build_worker_prompt
        # YAL has a verified apply procedure in data/company_apply_procedures/yal.json
        prompt = build_worker_prompt(
            company="YAL",
            title="AI Engineer",
            url="https://www.linkedin.com/jobs/view/4481345852/",
            job_id="test_yal_01",
            is_resume=True
        )
        self.assertIn("EXISTING MEMORIZED PROCEDURE FOR YAL", prompt)
        self.assertIn("linkedin_easy_apply", prompt)

    def test_delegator_uses_medium_effort(self):
        import engine.agent_delegator as ad
        import inspect
        src = inspect.getsource(ad.delegate_job_to_agent)
        self.assertIn('"--effort", "medium"', src)
        self.assertNotIn('"--effort", "high"', src)


if __name__ == "__main__":
    unittest.main()
