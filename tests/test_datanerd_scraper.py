import unittest
from engine.scraper import clean_company_name, pick_best_apply_url, format_datanerd_salary, scrape_datanerd

class TestDataNerdScraper(unittest.TestCase):
    def test_clean_company_name(self):
        self.assertEqual(clean_company_name("1203 Barclays Global Serv. Cent"), "Barclays")
        self.assertEqual(clean_company_name("6221 Roche Information Solutions India Private Limited"), "Roche")
        self.assertEqual(clean_company_name("7018 Jiostar India Private Limited"), "Jiostar")
        self.assertEqual(clean_company_name("ALPHA IT CONSULTANTS PVT LTD"), "ALPHA IT CONSULTANTS")
        self.assertEqual(clean_company_name("Quantabase Technologies"), "Quantabase Technologies")

    def test_pick_best_apply_url(self):
        options = [
            {"title": "Jobaaj", "link": "https://jobaaj.com/job/123"},
            {"title": "LinkedIn", "link": "https://in.linkedin.com/jobs/view/456"},
            {"title": "Workday", "link": "https://barclays.wd3.myworkdayjobs.com/job/789"}
        ]
        best = pick_best_apply_url(options, "https://google.com/search", "https://datanerd.tech")
        self.assertEqual(best, "https://barclays.wd3.myworkdayjobs.com/job/789")

        # Fallback to LinkedIn when no ATS
        options_no_ats = [
            {"title": "Indeed", "link": "https://in.indeed.com/viewjob?jk=123"},
            {"title": "LinkedIn", "link": "https://in.linkedin.com/jobs/view/456"}
        ]
        best_li = pick_best_apply_url(options_no_ats, "https://google.com/search", "https://datanerd.tech")
        self.assertEqual(best_li, "https://in.linkedin.com/jobs/view/456")

    def test_format_datanerd_salary(self):
        # Full INR values to LPA
        self.assertEqual(format_datanerd_salary(None, 2600000.0, None, "INR", "year"), "₹26.0 LPA")
        self.assertEqual(format_datanerd_salary(2000000.0, None, 3200000.0, "INR", "year"), "₹20.0 - ₹32.0 LPA")
        # Direct LPA number
        self.assertEqual(format_datanerd_salary(None, 35.0, None, "INR", "year"), "₹35.0 LPA")

    def test_scrape_datanerd_structure(self):
        # Test scraping with a small limit
        jobs = scrape_datanerd(title="Data Engineer", country="India", days_back=90, limit=3)
        self.assertIsInstance(jobs, list)
        if jobs:
            j = jobs[0]
            self.assertTrue(j["job_id"].startswith("dnerd_"))
            self.assertEqual(j["source"], "datanerd")
            self.assertTrue(len(j["canonical_hash"]) >= 16)
            self.assertIn("India", j["location"])
            self.assertTrue(j["url"].startswith("http"))
            self.assertIn("source_url", j["metadata"])
            self.assertIn("https://datanerd.tech/jobs?title=Data%20Engineer&country=India", j["metadata"]["source_url"])

if __name__ == "__main__":
    unittest.main()
