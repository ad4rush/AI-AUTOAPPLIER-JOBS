import unittest
from engine.evaluator import evaluate_job_match, parse_experience_requirements
from engine.chatgpt_consultant import _fallback_job_evaluation

class TestEvaluatorExperienceAndGates(unittest.TestCase):
    def test_parse_experience_requirements(self):
        self.assertEqual(parse_experience_requirements("requires 5+ years of experience")[0], 5)
        self.assertEqual(parse_experience_requirements("minimum 3 years in python")[0], 3)
        self.assertEqual(parse_experience_requirements("3-5 years building distributed systems")[0], 3)
        self.assertEqual(parse_experience_requirements("at least 7 years of hands-on spark")[0], 7)
        self.assertEqual(parse_experience_requirements("0-2 years or new graduate")[0], 0)
        self.assertEqual(parse_experience_requirements("experience: 4+ yrs")[0], 4)

    def test_stub_jd_handled_as_normal_eval(self):
        # Generic tech title with stub description gets standard calibrated evaluation (NORMAL, not immediate SKIP)
        res = evaluate_job_match("Apple", "Data & AI Engineer - Find My", "Apple | Data & AI Engineer - Find My | Hyderabad", "Hyderabad, India")
        self.assertEqual(res["priority_level"], "NORMAL")
        self.assertEqual(res["match_score"], 55)

    def test_high_experience_rejection(self):
        # Explicit 5+ years requirement must be rejected
        full_jd = "We are seeking an engineer with minimum 5+ years of experience in distributed systems and PyTorch."
        res = evaluate_job_match("Apple", "Data & AI Engineer", full_jd)
        self.assertEqual(res["priority_level"], "SKIP")
        self.assertEqual(res["fit_verdict"], "HIGH_EXPERIENCE_EXCLUDED")
        self.assertLessEqual(res["match_score"], 20)

    def test_senior_title_rejection(self):
        # Senior title without early career keywords must be rejected
        res = evaluate_job_match("Stripe", "Senior Software Engineer", "Python, REST APIs, PostgreSQL.")
        self.assertEqual(res["priority_level"], "SKIP")
        self.assertEqual(res["fit_verdict"], "SENIOR_TITLE_EXCLUDED")

    def test_early_career_approved(self):
        # 0-2 years early career role must be eligible
        full_jd = "Entry level position for new graduates (0-2 years). Work with Python, Kafka, and PyTorch."
        res = evaluate_job_match("Microsoft", "Associate Software Engineer", full_jd, "India")
        self.assertIn(res["priority_level"], ("HIGH_PRIORITY", "CRITICAL_PRIORITY", "NORMAL"))
        self.assertGreaterEqual(res["match_score"], 60)

    def test_fallback_ai_evaluation_gates(self):
        # Fallback AI evaluation must reject senior roles
        fb_senior = _fallback_job_evaluation("Google", "Staff Software Engineer", "Python, Kubernetes")
        self.assertFalse(fb_senior["should_apply"])

        # Fallback AI evaluation must reject 5+ yr roles
        fb_high_exp = _fallback_job_evaluation("Meta", "Software Engineer", "Requirements: 5+ years of experience with PyTorch.")
        self.assertFalse(fb_high_exp["should_apply"])

if __name__ == "__main__":
    unittest.main()
